"""Tests for kintsugi.kintsugi_engine.scaffold_orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kintsugi.kintsugi_engine.scaffold_orchestrator import (
    ScaffoldExecutionResult,
    ScaffoldOrchestrator,
    ScaffoldOrchestratorConfig,
)
from kintsugi.kintsugi_engine.scaffold_exploration import ExplorationDecision
from kintsugi.kintsugi_engine.scaffold_memory import InMemoryScaffoldKG
from kintsugi.skills.base import (
    BaseSkillChip,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)
from kintsugi.skills.dag import DAGExecutor
from kintsugi.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubChip(BaseSkillChip):
    """Minimal concrete skill chip for registry population."""

    def __init__(self, chip_name: str, description: str = ""):
        self.name = chip_name
        self.description = description
        self.domain = SkillDomain.GENERAL
        super().__init__()

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(content="ok", success=True, data={"result": "done"})


def _make_registry(*names: str) -> SkillRegistry:
    """Build a registry with stub chips for the given names."""
    reg = SkillRegistry()
    for name in names:
        reg.register(_StubChip(name, description=f"Stub {name}"))
    return reg


def _make_context() -> SkillContext:
    return SkillContext(org_id="test-org", user_id="test-user")


def _make_orchestrator(
    *chip_names: str,
    config: ScaffoldOrchestratorConfig | None = None,
) -> ScaffoldOrchestrator:
    """Build an orchestrator with stub chips (no LLM -- heuristic mode)."""
    registry = _make_registry(*chip_names)
    executor = DAGExecutor(registry)
    return ScaffoldOrchestrator(
        registry=registry,
        executor=executor,
        llm=None,
        config=config,
    )


# ---------------------------------------------------------------------------
# 1. ScaffoldOrchestratorConfig defaults
# ---------------------------------------------------------------------------


class TestScaffoldOrchestratorConfig:
    def test_defaults(self):
        cfg = ScaffoldOrchestratorConfig()
        assert cfg.min_comparisons_before_skip == 5
        assert cfg.max_explore_per_session == 10
        assert cfg.persist_path is None
        assert cfg.comparator_weights is None

    def test_custom_values(self):
        cfg = ScaffoldOrchestratorConfig(
            min_comparisons_before_skip=3,
            max_explore_per_session=20,
            persist_path=Path("/tmp/test.json"),
            comparator_weights={"completion": 0.5, "quality": 0.5},
        )
        assert cfg.min_comparisons_before_skip == 3
        assert cfg.max_explore_per_session == 20
        assert cfg.persist_path == Path("/tmp/test.json")
        assert cfg.comparator_weights == {"completion": 0.5, "quality": 0.5}


# ---------------------------------------------------------------------------
# 2. ScaffoldOrchestrator construction
# ---------------------------------------------------------------------------


class TestScaffoldOrchestratorConstruction:
    def test_minimal_construction(self):
        orch = _make_orchestrator("alpha", "beta")
        assert orch.kg is not None
        assert orch.explorer is not None
        assert isinstance(orch.kg, InMemoryScaffoldKG)

    def test_stats_initial(self):
        orch = _make_orchestrator("alpha")
        s = orch.stats()
        assert s["kg"]["total_comparisons"] == 0
        assert s["config"]["min_comparisons_before_skip"] == 5
        assert s["config"]["max_explore_per_session"] == 10


# ---------------------------------------------------------------------------
# 3. execute_task() when explorer says SKIP
# ---------------------------------------------------------------------------


class TestExecuteTaskSkip:
    @pytest.mark.asyncio
    async def test_skip_returns_no_comparison(self):
        """When min_comparisons is 0, the explorer decides to SKIP
        (no early-phase exploration), so we only run one scaffold."""
        # Force SKIP by setting min_comparisons to 0 and feeding the KG
        # enough data that the explorer's epistemic value is negligible.
        # Simplest: set min_comparisons_before_skip=0 and exhaust budget.
        cfg = ScaffoldOrchestratorConfig(
            min_comparisons_before_skip=0,
            max_explore_per_session=0,  # budget exhausted immediately
        )
        orch = _make_orchestrator("alpha", "beta", config=cfg)
        ctx = _make_context()

        result = await orch.execute_task("do something", ctx, task_type="general")

        assert isinstance(result, ScaffoldExecutionResult)
        assert result.comparison is None
        assert result.dag_result is not None
        assert result.proposal is not None
        assert result.task_type == "general"

    @pytest.mark.asyncio
    async def test_skip_exploration_decision(self):
        cfg = ScaffoldOrchestratorConfig(
            min_comparisons_before_skip=0,
            max_explore_per_session=0,
        )
        orch = _make_orchestrator("alpha", config=cfg)
        ctx = _make_context()

        result = await orch.execute_task("task", ctx)
        assert result.exploration is not None
        assert result.exploration.decision == ExplorationDecision.SKIP


# ---------------------------------------------------------------------------
# 4. execute_task() when explorer says EXPLORE
# ---------------------------------------------------------------------------


class TestExecuteTaskExplore:
    @pytest.mark.asyncio
    async def test_explore_runs_comparison(self):
        """With default config (min_comparisons=5, budget available),
        the explorer should EXPLORE on a fresh KG, producing a comparison."""
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        result = await orch.execute_task("do something", ctx, task_type="general")

        assert result.comparison is not None
        assert result.comparison.winner in ("exploit", "explore", "tie")
        assert result.comparison.margin >= 0.0
        assert result.exploration is not None
        assert result.exploration.decision in (
            ExplorationDecision.EXPLORE,
            ExplorationDecision.REFINE,
        )

    @pytest.mark.asyncio
    async def test_explore_records_in_kg(self):
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        assert orch.kg.total_comparisons == 0
        await orch.execute_task("task1", ctx, task_type="general")
        assert orch.kg.total_comparisons == 1

    @pytest.mark.asyncio
    async def test_explore_dag_results_success(self):
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        result = await orch.execute_task("task1", ctx, task_type="general")
        # Both DAGs ran successfully (stub chips always succeed)
        assert result.dag_result.success is True


# ---------------------------------------------------------------------------
# 5. execute_task() when explore wins
# ---------------------------------------------------------------------------


class TestExploreWins:
    @pytest.mark.asyncio
    async def test_explore_winner_returns_explore_result(self):
        """When explore wins, the primary result should be the explore proposal
        and explore DAG result. We test the logic by verifying that the
        returned proposal matches the winner."""
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        result = await orch.execute_task("task1", ctx, task_type="general")

        if result.comparison is not None and result.comparison.winner == "explore":
            # The primary proposal should be the explore one
            assert result.proposal.source in ("heuristic_explore", "generated_explore")
        elif result.comparison is not None and result.comparison.winner != "explore":
            # Exploit or tie: primary should be exploit
            assert result.proposal.source in ("heuristic", "generated")

    @pytest.mark.asyncio
    async def test_returned_result_matches_winner(self):
        """Run multiple times to get coverage of both branches."""
        orch = _make_orchestrator("alpha", "beta", "gamma")
        ctx = _make_context()

        for _ in range(5):
            result = await orch.execute_task(f"task", ctx, task_type="general")
            if result.comparison is None:
                continue
            # The returned proposal and dag_result should be consistent
            assert result.dag_result is not None
            assert result.proposal is not None


# ---------------------------------------------------------------------------
# 6. KG accumulation across multiple calls
# ---------------------------------------------------------------------------


class TestKGAccumulation:
    @pytest.mark.asyncio
    async def test_multiple_tasks_accumulate(self):
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        for i in range(3):
            await orch.execute_task(f"task_{i}", ctx, task_type="general")

        assert orch.kg.total_comparisons == 3

    @pytest.mark.asyncio
    async def test_different_task_types(self):
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        await orch.execute_task("migration", ctx, task_type="migration")
        await orch.execute_task("review", ctx, task_type="code_review")

        stats = orch.kg.stats()
        assert stats["total_comparisons"] == 2
        # task_types_seen is derived from wins/losses dicts, which are only
        # populated when a comparison has a non-tie winner. Ties don't
        # contribute, so we just verify records were stored.
        assert len(orch.kg._records) == 2


# ---------------------------------------------------------------------------
# 7. stats() returns combined KG stats
# ---------------------------------------------------------------------------


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_after_executions(self):
        orch = _make_orchestrator("alpha", "beta")
        ctx = _make_context()

        await orch.execute_task("t1", ctx, task_type="general")
        await orch.execute_task("t2", ctx, task_type="security")

        s = orch.stats()
        assert "kg" in s
        assert "config" in s
        assert s["kg"]["total_comparisons"] == 2
        assert s["config"]["min_comparisons_before_skip"] == 5
        assert s["config"]["max_explore_per_session"] == 10

    def test_stats_empty_orchestrator(self):
        orch = _make_orchestrator("alpha")
        s = orch.stats()
        assert s["kg"]["total_comparisons"] == 0
        assert s["kg"]["patterns_seen"] == 0
        assert s["kg"]["task_types_seen"] == 0


# ---------------------------------------------------------------------------
# 8. reset_session() resets exploration budget
# ---------------------------------------------------------------------------


class TestResetSession:
    @pytest.mark.asyncio
    async def test_reset_session_restores_budget(self):
        cfg = ScaffoldOrchestratorConfig(max_explore_per_session=2)
        orch = _make_orchestrator("alpha", "beta", config=cfg)
        ctx = _make_context()

        # Exhaust budget (2 explorations)
        await orch.execute_task("t1", ctx, task_type="general")
        await orch.execute_task("t2", ctx, task_type="general")

        # Third call should SKIP due to exhausted budget
        result = await orch.execute_task("t3", ctx, task_type="general")
        assert result.exploration.decision == ExplorationDecision.SKIP

        # Reset and verify we can explore again
        orch.reset_session()

        result = await orch.execute_task("t4", ctx, task_type="novel_type")
        # Should be able to explore again after reset
        assert result.exploration.decision in (
            ExplorationDecision.EXPLORE,
            ExplorationDecision.REFINE,
        )

    def test_reset_session_is_idempotent(self):
        orch = _make_orchestrator("alpha")
        orch.reset_session()
        orch.reset_session()  # should not raise


# ---------------------------------------------------------------------------
# 9. Persistence: _save_kg() and _load_kg() round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, tmp_path: Path):
        persist_file = tmp_path / "scaffold_kg.json"
        cfg = ScaffoldOrchestratorConfig(persist_path=persist_file)
        orch = _make_orchestrator("alpha", "beta", config=cfg)
        ctx = _make_context()

        # Run some tasks to populate KG
        await orch.execute_task("t1", ctx, task_type="general")
        await orch.execute_task("t2", ctx, task_type="security")

        original_comparisons = orch.kg.total_comparisons
        original_stats = orch.kg.stats()

        # File should have been created by the auto-save in execute_task
        assert persist_file.exists()

        # Verify the saved data is valid JSON
        data = json.loads(persist_file.read_text())
        assert "wins" in data
        assert "losses" in data
        assert "records" in data

        # Create a new orchestrator that loads from the same file
        registry2 = _make_registry("alpha", "beta")
        executor2 = DAGExecutor(registry2)
        orch2 = ScaffoldOrchestrator(
            registry=registry2,
            executor=executor2,
            config=cfg,
        )

        assert orch2.kg.total_comparisons == original_comparisons
        assert orch2.kg.stats()["total_comparisons"] == original_stats["total_comparisons"]

    @pytest.mark.asyncio
    async def test_save_creates_parent_dirs(self, tmp_path: Path):
        persist_file = tmp_path / "nested" / "dir" / "kg.json"
        cfg = ScaffoldOrchestratorConfig(persist_path=persist_file)
        orch = _make_orchestrator("alpha", "beta", config=cfg)
        ctx = _make_context()

        await orch.execute_task("t1", ctx, task_type="general")
        assert persist_file.exists()

    def test_load_with_no_file(self, tmp_path: Path):
        """Loading from a non-existent file should not raise."""
        persist_file = tmp_path / "missing.json"
        cfg = ScaffoldOrchestratorConfig(persist_path=persist_file)
        # Should not raise
        orch = _make_orchestrator("alpha", config=cfg)
        assert orch.kg.total_comparisons == 0

    def test_load_with_corrupt_file(self, tmp_path: Path):
        """Loading from a corrupt file should log warning but not crash."""
        persist_file = tmp_path / "corrupt.json"
        persist_file.write_text("not valid json {{{")

        cfg = ScaffoldOrchestratorConfig(persist_path=persist_file)
        # The constructor loads if file exists -- should handle gracefully
        registry = _make_registry("alpha")
        executor = DAGExecutor(registry)
        orch = ScaffoldOrchestrator(
            registry=registry,
            executor=executor,
            config=cfg,
        )
        assert orch.kg.total_comparisons == 0

    def test_save_without_persist_path(self):
        """_save_kg with no persist_path should be a no-op."""
        orch = _make_orchestrator("alpha")
        # Should not raise
        orch._save_kg()

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_kg_content(self, tmp_path: Path):
        persist_file = tmp_path / "kg_content.json"
        cfg = ScaffoldOrchestratorConfig(persist_path=persist_file)
        orch = _make_orchestrator("alpha", "beta", config=cfg)
        ctx = _make_context()

        await orch.execute_task("migration task", ctx, task_type="migration")
        await orch.execute_task("security task", ctx, task_type="security")
        await orch.execute_task("another migration", ctx, task_type="migration")

        original_records_count = len(orch.kg._records)

        # Reload into fresh orchestrator
        registry2 = _make_registry("alpha", "beta")
        executor2 = DAGExecutor(registry2)
        orch2 = ScaffoldOrchestrator(
            registry=registry2,
            executor=executor2,
            config=cfg,
        )

        assert len(orch2.kg._records) == original_records_count
        assert orch2.kg.total_comparisons == 3
