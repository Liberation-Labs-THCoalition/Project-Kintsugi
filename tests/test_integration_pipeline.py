"""Integration smoke tests for the full Kintsugi request pipeline.

These tests exercise end-to-end flows through multiple subsystems:
orchestrator routing, EFE scoring, skill dispatch, shadow fork execution,
and security invariant checking.  All tests mock the LLM client so they
run without network access.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from kintsugi.cognition.efe import EFECalculator, EFEScore
from kintsugi.cognition.model_router import ModelTier
from kintsugi.cognition.orchestrator import (
    DOMAIN_EFE_WEIGHTS,
    Orchestrator,
    OrchestratorConfig,
    RoutingDecision,
)
from kintsugi.kintsugi_engine.evolution import (
    EvolutionManager,
    ModificationScope,
)
from kintsugi.kintsugi_engine.shadow_fork import (
    OutputComparison,
    ShadowConfig,
    ShadowFork,
    ShadowStatus,
)
from kintsugi.kintsugi_engine.verifier import Verifier
from kintsugi.security.intent_capsule import (
    IntentCapsule,
    sign_capsule,
    verify_capsule,
)
from kintsugi.security.invariants import InvariantChecker, InvariantContext
from kintsugi.skills.base import BaseSkillChip, SkillContext, SkillDomain
from kintsugi.skills.registry import SkillRegistry
from kintsugi.skills.router import SkillRouter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator():
    return Orchestrator()


@pytest.fixture
def efe_calculator():
    return EFECalculator()


@pytest.fixture
def secret_key():
    return "test-secret-key-for-invariants"


class _StubChip(BaseSkillChip):
    """Minimal skill chip for testing."""

    def __init__(self, chip_name: str, domain: SkillDomain):
        super().__init__()
        self.name = chip_name
        self.description = f"Stub chip for {chip_name}"
        self.domain = domain

    async def handle(self, request, context):
        from kintsugi.skills.base import SkillResponse

        return SkillResponse(
            content=f"Handled by {self.name}",
            success=True,
        )


@pytest.fixture
def skill_registry():
    registry = SkillRegistry()
    registry.register(_StubChip("grant_search", SkillDomain.FUNDRAISING))
    registry.register(_StubChip("finance_assistant", SkillDomain.FINANCE))
    registry.register(_StubChip("content_drafter", SkillDomain.COMMUNICATIONS))
    return registry


@pytest.fixture
def skill_router(skill_registry):
    router = SkillRouter(skill_registry)
    router.register_intent("grant_search", "grant_search")
    router.register_intent("finance_assistant", "finance_assistant")
    router.register_intent("content_drafter", "content_drafter")
    return router


# ---------------------------------------------------------------------------
# 1. Routing smoke test
# ---------------------------------------------------------------------------


class TestRoutingSmokeTest:
    """Send a message through Orchestrator.route() and verify a valid
    RoutingDecision is returned with a known skill domain."""

    @pytest.mark.asyncio
    async def test_route_returns_valid_decision(self, orchestrator):
        decision = await orchestrator.route(
            message="We need to find grant funding for our program",
            org_id="org_test_123",
        )

        assert isinstance(decision, RoutingDecision)
        assert decision.skill_domain == "grants"
        assert decision.confidence > 0
        assert decision.model_tier in list(ModelTier)
        assert decision.reasoning

    @pytest.mark.asyncio
    async def test_route_finance_domain(self, orchestrator):
        decision = await orchestrator.route(
            message="Review the quarterly budget and expense report",
            org_id="org_test_123",
        )

        assert decision.skill_domain == "finance"
        assert decision.model_tier in (ModelTier.BALANCED, ModelTier.POWERFUL)

    @pytest.mark.asyncio
    async def test_route_fallback_for_unknown_topic(self, orchestrator):
        decision = await orchestrator.route(
            message="Hello, how are you today?",
            org_id="org_test_123",
        )

        assert decision.skill_domain == "general"


# ---------------------------------------------------------------------------
# 2. Skill execution smoke test
# ---------------------------------------------------------------------------


class TestSkillExecutionSmokeTest:
    """Route a message to a skill chip via the SkillRouter, call
    chip.handle(), and verify a SkillResponse is returned."""

    def test_router_resolves_chip(self, skill_router):
        match = skill_router.route("grant_search")

        assert match is not None
        assert match.chip.name == "grant_search"
        assert match.confidence > 0

    @pytest.mark.asyncio
    async def test_chip_handle_returns_response(self, skill_router):
        match = skill_router.route("grant_search")
        assert match is not None

        context = SkillContext(
            org_id="org_test_123",
            user_id="user_456",
            platform="webchat",
        )

        response = await match.chip.handle("Find grants for education", context)
        assert response is not None
        assert response.content == "Handled by grant_search"
        assert response.success is True


# ---------------------------------------------------------------------------
# 3. EFE-informed routing test
# ---------------------------------------------------------------------------


class TestEFEInformedRouting:
    """Send an ambiguous message that matches multiple domains, verify
    EFE scoring is invoked and the decision includes score data."""

    @pytest.mark.asyncio
    async def test_ambiguous_query_uses_efe(self):
        orch = Orchestrator()
        # "budget proposal for grant funding" matches both finance and grants
        decision = await orch.classify_request(
            "We need a budget proposal for the grant funding application"
        )

        assert isinstance(decision, RoutingDecision)
        # EFE should have been invoked for multi-domain disambiguation
        assert decision.efe_score is not None
        assert isinstance(decision.efe_score, EFEScore)
        assert decision.efe_score.total is not None
        assert "EFE-selected" in decision.reasoning

    @pytest.mark.asyncio
    async def test_finance_query_gets_finance_weights(self):
        orch = Orchestrator()
        # "budget expense revenue" hits only finance
        decision = await orch.classify_request(
            "Review the budget expense and revenue report"
        )

        assert decision.skill_domain == "finance"

    @pytest.mark.asyncio
    async def test_high_risk_domain_routes_to_higher_tier(self):
        orch = Orchestrator()
        # Ambiguous query across finance (high risk weight) and grants
        decision = await orch.classify_request(
            "budget proposal funding grant expense financial"
        )

        # With EFE engagement, should not be FAST
        assert decision.model_tier in (ModelTier.BALANCED, ModelTier.POWERFUL)


# ---------------------------------------------------------------------------
# 4. Shadow fork integration test
# ---------------------------------------------------------------------------


class TestShadowForkIntegration:
    """Submit a modification proposal via EvolutionManager, activate it,
    run a shadow fork execution, and verify the verifier receives
    comparison data."""

    def test_evolution_to_shadow_fork_flow(self):
        # Step 1: Submit a proposal
        mgr = EvolutionManager()
        proposal = mgr.submit_proposal(
            scope=ModificationScope.PROMPT,
            description="Improve grant search prompt template",
            modification={"prompt_template": "Find grants for {topic}"},
        )
        assert proposal is not None
        assert proposal.status == "queued"

        # Step 2: Activate it
        activated = mgr.activate_next()
        assert activated is not None
        assert activated.status == "active"

        # Step 3: Run shadow fork with mock mode
        primary_config = {"model": "sonnet", "temperature": 0.7}
        shadow_config = ShadowConfig(
            modification=proposal.modification,
            mock_tool_responses={"search_grants": {"results": ["grant_a"]}},
        )
        fork = ShadowFork(primary_config, shadow_config)
        shadow_id = fork.fork()

        result = fork.execute_turn(shadow_id, "Find education grants")
        assert result["shadow_id"] == shadow_id
        assert "output" in result

        state = fork.terminate(shadow_id)
        assert state.status == ShadowStatus.COMPLETED

        # Step 4: Compare outputs
        primary_outputs = [{"text": "Found 3 grants", "tool_calls": []}]
        shadow_outputs = state.outputs
        comparison = ShadowFork.compare_outputs(
            primary_outputs, shadow_outputs
        )
        assert isinstance(comparison, OutputComparison)
        assert 0.0 <= comparison.response_similarity <= 1.0

        # Step 5: Feed to verifier
        verifier = Verifier()
        verdict = verifier.verify(
            primary_outputs=primary_outputs,
            shadow_outputs=shadow_outputs,
        )
        assert verdict is not None
        assert hasattr(verdict, "verdict")

    @pytest.mark.asyncio
    async def test_live_mode_with_mock_llm(self):
        """Live mode execution with a mock LLM client injected."""

        async def mock_llm_caller(prompt, config):
            return {
                "text": f"LLM response for: {prompt[:40]}",
                "tool_calls": [
                    {"tool": "search_grants", "input": prompt},
                ],
            }

        shadow_config = ShadowConfig(
            modification={"temperature": 0.9},
            mock_tool_responses={"search_grants": {"results": ["g1", "g2"]}},
            execute_mode="live",
        )
        fork = ShadowFork(
            {"model": "sonnet"},
            shadow_config,
            llm_caller=mock_llm_caller,
        )
        shadow_id = fork.fork()

        result = await fork.execute_turn_async(shadow_id, "Find grants")
        assert result["output"]["mode"] == "live"
        assert "LLM response" in result["output"]["response"]
        # Tool calls should be intercepted
        assert all(tc["intercepted"] for tc in result["tool_calls"])

    @pytest.mark.asyncio
    async def test_live_mode_timeout_enforcement(self):
        """Shadow with very short timeout should be terminated."""

        async def slow_llm_caller(prompt, config):
            await asyncio.sleep(5)
            return {"text": "should not reach here"}

        shadow_config = ShadowConfig(
            execute_mode="live",
            timeout_seconds=0.01,
        )
        fork = ShadowFork(
            {"model": "sonnet"},
            shadow_config,
            llm_caller=slow_llm_caller,
        )
        shadow_id = fork.fork()

        with pytest.raises(RuntimeError, match="exceeded resource limits"):
            await fork.execute_turn_async(shadow_id, "test")

        state = fork.get_state(shadow_id)
        assert state.status == ShadowStatus.TIMEOUT

    def test_compare_outputs_structured_diffs(self):
        """compare_outputs returns meaningful diffs."""
        primary = [
            {"text": "Found 3 grants for education"},
            {"tool": "search", "intercepted": True, "response": "ok"},
        ]
        shadow = [
            {"text": "Found 5 grants for education"},
            {"tool": "search", "intercepted": True, "response": "ok"},
            {"tool": "rank", "intercepted": True, "response": "ranked"},
        ]

        comparison = ShadowFork.compare_outputs(
            primary, shadow, primary_elapsed=1.0, shadow_elapsed=1.5
        )
        assert comparison.response_similarity < 1.0
        assert comparison.latency_delta_seconds == pytest.approx(0.5)
        assert len(comparison.tool_call_differences) > 0
        assert comparison.summary


# ---------------------------------------------------------------------------
# 5. Security invariant test
# ---------------------------------------------------------------------------


class TestSecurityInvariant:
    """Create an InvariantContext with a valid IntentCapsule, run
    InvariantChecker.check_all(), verify it passes.  Then create one
    with an expired capsule and verify it fails."""

    def test_valid_capsule_passes(self, secret_key):
        capsule = sign_capsule(
            goal="Find grants for education programs",
            constraints={"allowed_tools": ["search", "read"]},
            org_id="org_test_123",
            secret_key=secret_key,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        ctx = InvariantContext(
            capsule=capsule,
            secret_key=secret_key,
        )

        checker = InvariantChecker()
        result = checker.check_all(ctx)

        assert result.all_passed is True
        assert len(result.failures) == 0

    def test_expired_capsule_fails(self, secret_key):
        capsule = sign_capsule(
            goal="Find grants",
            constraints={},
            org_id="org_test_123",
            secret_key=secret_key,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        ctx = InvariantContext(
            capsule=capsule,
            secret_key=secret_key,
        )

        checker = InvariantChecker()
        result = checker.check_all(ctx)

        assert result.all_passed is False
        assert "intent_signature" in result.failures

    def test_budget_check_passes_within_limit(self):
        ctx = InvariantContext(
            cost=2.5,
            budget_remaining=5.0,
        )

        checker = InvariantChecker()
        result = checker.check_all(ctx)

        assert result.all_passed is True

    def test_budget_check_fails_over_limit(self):
        ctx = InvariantContext(
            cost=10.0,
            budget_remaining=5.0,
        )

        checker = InvariantChecker()
        result = checker.check_all(ctx)

        assert result.all_passed is False
        assert "budget" in result.failures
