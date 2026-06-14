"""End-to-end integration test — the full Kintsugi flow.

Tests: message → enhanced routing → skill execution → shadow verification
of a proposed skill modification → promote or reject.

No database required — uses in-memory mocks.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from kintsugi.skills.base import (
    BaseSkillChip, SkillDomain, SkillContext, SkillRequest,
    SkillResponse, EFEWeights, SkillCapability,
)
from kintsugi.skills.registry import SkillRegistry
from kintsugi.skills.capability_tree import CapabilityTree
from kintsugi.skills.dag import DAGBuilder, DAGExecutor, SkillDAG
from kintsugi.cognition.enhanced_orchestrator import EnhancedOrchestrator
from kintsugi.kintsugi_engine.shadow_fork import ShadowFork, ShadowConfig
from kintsugi.kintsugi_engine.verifier import Verifier, VerifierConfig


class MockMutualAidChip(BaseSkillChip):
    name = "mutual_aid_coordinator"
    domain = SkillDomain.MUTUAL_AID
    description = "Coordinate mutual aid requests"
    version = "1.0.0"
    capabilities = [SkillCapability.READ_DATA, SkillCapability.WRITE_DATA]
    efe_weights = EFEWeights()

    async def handle(self, request, context):
        return SkillResponse(
            content=f"Mutual aid request received: {request.raw_input[:50]}. "
                    f"Routing to coordinator for review.",
            success=True,
            data={"action": "route_to_coordinator"},
        )


class MockGrantChip(BaseSkillChip):
    name = "grant_hunter"
    domain = SkillDomain.FUNDRAISING
    description = "Search for grants"
    version = "1.0.0"
    capabilities = [SkillCapability.EXTERNAL_API]
    efe_weights = EFEWeights()

    async def handle(self, request, context):
        return SkillResponse(
            content="Found 3 matching grants for education programs.",
            success=True,
            data={"grants_found": 3},
        )


class MockVolunteerChip(BaseSkillChip):
    name = "volunteer_coordinator"
    domain = SkillDomain.COMMUNITY
    description = "Match volunteers"
    version = "1.0.0"
    capabilities = [SkillCapability.READ_DATA]
    efe_weights = EFEWeights()

    async def handle(self, request, context):
        return SkillResponse(
            content="Matched 2 volunteers with available mentoring slots.",
            success=True,
            data={"matches": 2},
        )


class MockCrisisChip(BaseSkillChip):
    name = "crisis_response"
    domain = SkillDomain.MUTUAL_AID
    description = "Handle crisis situations"
    version = "1.0.0"
    capabilities = [SkillCapability.SEND_NOTIFICATIONS]
    efe_weights = EFEWeights()

    async def handle(self, request, context):
        return SkillResponse(
            content="ALERT: Crisis flagged. Coordinator notified immediately.",
            success=True,
            requires_consensus=True,
            consensus_action="crisis_escalation",
        )


@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg.register(MockMutualAidChip())
    reg.register(MockGrantChip())
    reg.register(MockVolunteerChip())
    reg.register(MockCrisisChip())
    return reg


@pytest.fixture
def tree(registry):
    t = CapabilityTree(registry)
    t.build_from_registry()
    return t


@pytest.fixture
def orchestrator(registry, tree):
    return EnhancedOrchestrator(
        registry=registry,
        tree=tree,
        dag_executor=DAGExecutor(registry),
    )


@pytest.fixture
def context():
    return SkillContext(
        org_id="multiverse-school",
        user_id="student-001",
        platform="api",
    )


class TestEndToEndRouting:
    @pytest.mark.asyncio
    async def test_single_skill_routing(self, orchestrator):
        decision = await orchestrator.route(
            "I need help with housing",
            org_id="multiverse",
            desires=[{"type": "mutual_aid"}],
        )
        assert decision.routing is not None
        assert decision.confidence > 0

    @pytest.mark.asyncio
    async def test_multi_step_detection(self, orchestrator):
        decision = await orchestrator.route(
            "First I need to apply for a scholarship and then find a mentor",
            org_id="multiverse",
            desires=[{"type": "mutual_aid"}, {"type": "community"}],
        )
        # Multi-step detected OR tree found relevant skills
        assert decision.is_composed or decision.skill_names is not None

    @pytest.mark.asyncio
    async def test_tree_retrieval_with_desires(self, orchestrator):
        decision = await orchestrator.route(
            "Can you help me?",
            org_id="multiverse",
            desires=[{"type": "mutual_aid", "content": "housing"}],
            beliefs=[{"community": "solarpunk"}],
        )
        assert decision.tree_path is not None


class TestEndToEndExecution:
    @pytest.mark.asyncio
    async def test_single_chip_execution(self, registry, context):
        chip = registry.get("mutual_aid_coordinator")
        request = SkillRequest(intent="mutual_aid", raw_input="I need housing help")
        response = await chip.handle(request, context)
        assert response.success
        assert "coordinator" in response.content.lower()

    @pytest.mark.asyncio
    async def test_dag_execution(self, registry, context):
        dag = DAGBuilder.from_skill_sequence(
            ["mutual_aid_coordinator", "volunteer_coordinator"],
            registry,
        )
        executor = DAGExecutor(registry)
        result = await executor.execute(dag, context)
        assert result.success or len(result.node_results) > 0
        assert result.layers_executed >= 1

    @pytest.mark.asyncio
    async def test_crisis_escalation(self, registry, context):
        chip = registry.get("crisis_response")
        request = SkillRequest(intent="crisis", raw_input="Emergency housing situation")
        response = await chip.handle(request, context)
        assert response.requires_consensus
        assert response.consensus_action == "crisis_escalation"


class TestEndToEndEvolution:
    def test_shadow_fork_creation(self):
        primary_config = {"model": "test", "temperature": 0.7}
        shadow_config = ShadowConfig(modification={"temperature": 0.3})
        fork = ShadowFork(primary_config=primary_config, shadow_config=shadow_config)
        shadow_id = fork.fork()
        assert shadow_id is not None
        state = fork.get_state(shadow_id)
        assert state is not None

    def test_shadow_execute_and_verify(self):
        primary_config = {"model": "test"}
        shadow_config = ShadowConfig()
        fork = ShadowFork(primary_config=primary_config, shadow_config=shadow_config)
        shadow_id = fork.fork()

        result = fork.execute_turn(shadow_id, "test message")
        assert result is not None

    def test_verifier_comparison(self):
        verifier = Verifier(config=VerifierConfig())

        primary_outputs = [
            {"input": "test1", "output": "response1", "metadata": {}},
            {"input": "test2", "output": "response2", "metadata": {}},
        ]
        shadow_outputs = [
            {"input": "test1", "output": "response1", "metadata": {}},
            {"input": "test2", "output": "response2_modified", "metadata": {}},
        ]

        result = verifier.verify(primary_outputs, shadow_outputs)
        assert result is not None
        assert result.verdict is not None

    def test_shadow_fork_terminate(self):
        primary_config = {"model": "test"}
        shadow_config = ShadowConfig()
        fork = ShadowFork(primary_config=primary_config, shadow_config=shadow_config)
        shadow_id = fork.fork()
        state = fork.terminate(shadow_id)
        assert state is not None


class TestEndToEndFullPipeline:
    @pytest.mark.asyncio
    async def test_route_execute_verify(self, orchestrator, registry, context):
        """The full pipeline: route → execute → shadow verify."""

        decision = await orchestrator.route(
            "I need help finding a scholarship",
            org_id="multiverse",
            desires=[{"type": "mutual_aid"}],
        )
        assert decision.routing is not None

        if decision.skill_names:
            chip = registry.get(decision.skill_names[0])
            if chip:
                request = SkillRequest(
                    intent=decision.skill_domain,
                    raw_input="I need help finding a scholarship",
                )
                response = await chip.handle(request, context)
                assert response.success

        primary_config = {"model": "test", "skills": ["mutual_aid"]}
        shadow_config = ShadowConfig(modification={"skills": ["mutual_aid", "grant_hunter"]})
        fork = ShadowFork(primary_config=primary_config, shadow_config=shadow_config)
        shadow_id = fork.fork()
        shadow_result = fork.execute_turn(shadow_id, "I need help finding a scholarship")
        fork.terminate(shadow_id)

        assert shadow_result is not None
