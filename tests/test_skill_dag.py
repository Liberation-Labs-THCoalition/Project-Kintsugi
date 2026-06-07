"""
Tests for the skill DAG module.

Tests DAG creation, validation, topological sort, layer-parallel execution,
failure handling, and the DAGBuilder utilities.
"""

import asyncio
import pytest

from kintsugi.skills.base import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)
from kintsugi.skills.registry import SkillRegistry
from kintsugi.skills.dag import DAGBuilder, DAGExecutor, DAGNode, DAGResult, SkillDAG


# ============================================================================
# Mock Skill Chips
# ============================================================================


class MockChip(BaseSkillChip):
    """Configurable mock skill chip for DAG tests."""

    def __init__(
        self,
        name: str,
        domain: SkillDomain = SkillDomain.OPERATIONS,
        description: str = "",
        response_data: dict | None = None,
        fail: bool = False,
        delay: float = 0.0,
    ):
        self.name = name
        self.domain = domain
        self.description = description or f"Mock chip: {name}"
        self.capabilities = []
        self.version = "1.0.0"
        self.efe_weights = EFEWeights()
        self.consensus_actions = []
        self.required_spans = []
        self._response_data = response_data or {}
        self._fail = fail
        self._delay = delay
        self.call_count = 0

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        self.call_count += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError(f"Intentional failure in {self.name}")
        return SkillResponse(
            content=f"Response from {self.name}",
            success=True,
            data=self._response_data,
        )


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def registry():
    """Fresh SkillRegistry for each test."""
    return SkillRegistry()


@pytest.fixture
def context():
    """Basic SkillContext for execution tests."""
    return SkillContext(org_id="org_test", user_id="user_test")


@pytest.fixture
def chip_a():
    return MockChip("chip_a", response_data={"result_a": "value_a"})


@pytest.fixture
def chip_b():
    return MockChip("chip_b", response_data={"result_b": "value_b"})


@pytest.fixture
def chip_c():
    return MockChip("chip_c", response_data={"result_c": "value_c"})


@pytest.fixture
def three_chip_registry(registry, chip_a, chip_b, chip_c):
    """Registry with three chips registered."""
    registry.register(chip_a)
    registry.register(chip_b)
    registry.register(chip_c)
    return registry


# ============================================================================
# Test: dag_creation
# ============================================================================


class TestDAGCreation:
    def test_dag_creation_basic(self):
        """Basic DAG can be created with nodes and edges."""
        dag = SkillDAG()

        node_a = DAGNode(node_id="a", skill_name="chip_a", sub_task="step_a", layer=0)
        node_b = DAGNode(node_id="b", skill_name="chip_b", sub_task="step_b", layer=1)

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_edge("a", "b")

        assert "a" in dag.nodes
        assert "b" in dag.nodes
        assert ("a", "b") in dag.edges

    def test_dag_has_unique_id(self):
        """Each DAG gets a unique ID."""
        dag1 = SkillDAG()
        dag2 = SkillDAG()
        assert dag1.dag_id != dag2.dag_id


# ============================================================================
# Test: dag_layers
# ============================================================================


class TestDAGLayers:
    def test_dag_layers_grouping(self):
        """Nodes are grouped correctly by layer."""
        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="a", skill_name="s", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="b", skill_name="s", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="c", skill_name="s", sub_task="t", layer=1))
        dag.add_node(DAGNode(node_id="d", skill_name="s", sub_task="t", layer=2))

        layers = dag.layers()

        assert len(layers) == 3
        assert set(layers[0]) == {"a", "b"}
        assert layers[1] == ["c"]
        assert layers[2] == ["d"]

    def test_dag_layers_empty(self):
        """Empty DAG has no layers."""
        dag = SkillDAG()
        assert dag.layers() == []


# ============================================================================
# Test: dag_validate_missing_skill
# ============================================================================


class TestDAGValidateMissingSkill:
    def test_dag_validate_missing_skill(self, registry, chip_a):
        """Validation catches missing skill references."""
        registry.register(chip_a)

        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="a", skill_name="chip_a", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="b", skill_name="nonexistent", sub_task="t", layer=1))
        dag.add_edge("a", "b")

        errors = dag.validate(registry)

        assert len(errors) > 0
        assert any("nonexistent" in e for e in errors)


# ============================================================================
# Test: dag_validate_cycle
# ============================================================================


class TestDAGValidateCycle:
    def test_dag_validate_cycle(self, three_chip_registry):
        """Validation catches circular dependencies via layer ordering."""
        dag = SkillDAG()
        # Create nodes where edges violate layer ordering (simulates cycle-like structure)
        dag.add_node(DAGNode(node_id="a", skill_name="chip_a", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="b", skill_name="chip_b", sub_task="t", layer=1))
        # Edge from layer 1 back to layer 0 — invalid
        dag.add_edge("b", "a")

        errors = dag.validate(three_chip_registry)

        assert len(errors) > 0
        assert any("layer" in e.lower() for e in errors)


# ============================================================================
# Test: dag_topological_sort
# ============================================================================


class TestDAGTopologicalSort:
    def test_dag_topological_sort_linear(self):
        """Linear DAG gives correct execution order."""
        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="a", skill_name="s", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="b", skill_name="s", sub_task="t", layer=1))
        dag.add_node(DAGNode(node_id="c", skill_name="s", sub_task="t", layer=2))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")

        order = dag.topological_sort()

        assert order == ["a", "b", "c"]

    def test_dag_topological_sort_diamond(self):
        """Diamond DAG respects all edges."""
        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="a", skill_name="s", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="b", skill_name="s", sub_task="t", layer=1))
        dag.add_node(DAGNode(node_id="c", skill_name="s", sub_task="t", layer=1))
        dag.add_node(DAGNode(node_id="d", skill_name="s", sub_task="t", layer=2))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        dag.add_edge("b", "d")
        dag.add_edge("c", "d")

        order = dag.topological_sort()

        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")


# ============================================================================
# Test: dag_executor_linear
# ============================================================================


class TestDAGExecutorLinear:
    @pytest.mark.asyncio
    async def test_dag_executor_linear(self, three_chip_registry, context):
        """Simple A->B->C chain executes in order."""
        dag = SkillDAG()
        dag.add_node(DAGNode(
            node_id="a", skill_name="chip_a", sub_task="step_a",
            layer=0, output_keys=["step_0_out"],
        ))
        dag.add_node(DAGNode(
            node_id="b", skill_name="chip_b", sub_task="step_b",
            layer=1, input_keys=["step_0_out"], output_keys=["step_1_out"],
        ))
        dag.add_node(DAGNode(
            node_id="c", skill_name="chip_c", sub_task="step_c",
            layer=2, input_keys=["step_1_out"], output_keys=["step_2_out"],
        ))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")

        executor = DAGExecutor(three_chip_registry)
        result = await executor.execute(dag, context)

        assert result.success is True
        assert "a" in result.node_results
        assert "b" in result.node_results
        assert "c" in result.node_results
        assert result.layers_executed == 3


# ============================================================================
# Test: dag_executor_parallel
# ============================================================================


class TestDAGExecutorParallel:
    @pytest.mark.asyncio
    async def test_dag_executor_parallel(self, context):
        """Same-layer nodes run concurrently."""
        registry = SkillRegistry()
        # Use delayed chips to verify parallel execution
        chip_a = MockChip("chip_a", delay=0.05)
        chip_b = MockChip("chip_b", delay=0.05)
        chip_c = MockChip("chip_c", delay=0.05)
        registry.register(chip_a)
        registry.register(chip_b)
        registry.register(chip_c)

        dag = SkillDAG()
        # All three in layer 0 — should run in parallel
        dag.add_node(DAGNode(node_id="a", skill_name="chip_a", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="b", skill_name="chip_b", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="c", skill_name="chip_c", sub_task="t", layer=0))

        executor = DAGExecutor(registry)
        result = await executor.execute(dag, context)

        assert result.success is True
        assert result.layers_executed == 1
        # If truly parallel, total time should be ~50ms, not ~150ms
        assert result.execution_time_ms < 120.0


# ============================================================================
# Test: dag_executor_failure
# ============================================================================


class TestDAGExecutorFailure:
    @pytest.mark.asyncio
    async def test_dag_executor_failure(self, context):
        """One node fails, others still execute, result is not success."""
        registry = SkillRegistry()
        registry.register(MockChip("chip_ok"))
        registry.register(MockChip("chip_fail", fail=True))

        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="ok", skill_name="chip_ok", sub_task="t", layer=0))
        dag.add_node(DAGNode(node_id="fail", skill_name="chip_fail", sub_task="t", layer=0))

        executor = DAGExecutor(registry)
        result = await executor.execute(dag, context)

        assert result.success is False
        assert "fail" in result.node_errors
        assert "ok" in result.node_results

    @pytest.mark.asyncio
    async def test_dag_executor_missing_skill_error(self, context):
        """Missing skill produces an error for that node."""
        registry = SkillRegistry()

        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="x", skill_name="missing", sub_task="t", layer=0))

        executor = DAGExecutor(registry)
        result = await executor.execute(dag, context)

        assert result.success is False
        assert "x" in result.node_errors
        assert "missing" in result.node_errors["x"].lower()


# ============================================================================
# Test: dag_from_skill_sequence
# ============================================================================


class TestDAGFromSkillSequence:
    def test_dag_from_skill_sequence(self, three_chip_registry):
        """DAGBuilder creates a linear chain from skill names."""
        dag = DAGBuilder.from_skill_sequence(
            ["chip_a", "chip_b", "chip_c"],
            three_chip_registry,
        )

        assert len(dag.nodes) == 3
        assert len(dag.edges) == 2

        # Verify linear edge structure
        assert ("node_0", "node_1") in dag.edges
        assert ("node_1", "node_2") in dag.edges

    def test_dag_from_skill_sequence_layers_are_sequential(self, three_chip_registry):
        """Each node in a sequence gets its own layer."""
        dag = DAGBuilder.from_skill_sequence(
            ["chip_a", "chip_b", "chip_c"],
            three_chip_registry,
        )

        assert dag.nodes["node_0"].layer == 0
        assert dag.nodes["node_1"].layer == 1
        assert dag.nodes["node_2"].layer == 2

    def test_dag_from_skill_sequence_with_sub_tasks(self, three_chip_registry):
        """Custom sub_tasks are assigned to nodes."""
        dag = DAGBuilder.from_skill_sequence(
            ["chip_a", "chip_b"],
            three_chip_registry,
            sub_tasks=["gather data", "process data"],
        )

        assert dag.nodes["node_0"].sub_task == "gather data"
        assert dag.nodes["node_1"].sub_task == "process data"

    def test_dag_from_skill_sequence_single_skill(self, three_chip_registry):
        """Single skill produces a DAG with one node, no edges."""
        dag = DAGBuilder.from_skill_sequence(["chip_a"], three_chip_registry)

        assert len(dag.nodes) == 1
        assert len(dag.edges) == 0


# ============================================================================
# Test: dag_result
# ============================================================================


class TestDAGResult:
    @pytest.mark.asyncio
    async def test_dag_result_has_artifacts(self, three_chip_registry, context):
        """DAGResult contains artifacts produced by executed nodes."""
        # chip_a produces response_data with result_a key
        chip_a = three_chip_registry.get("chip_a")
        chip_a._response_data = {"step_0_out": "artifact_value"}

        dag = SkillDAG()
        dag.add_node(DAGNode(
            node_id="a", skill_name="chip_a", sub_task="produce",
            layer=0, output_keys=["step_0_out"],
        ))

        executor = DAGExecutor(three_chip_registry)
        result = await executor.execute(dag, context)

        assert "step_0_out" in result.artifacts

    @pytest.mark.asyncio
    async def test_dag_result_has_timing(self, three_chip_registry, context):
        """DAGResult has execution_time_ms > 0."""
        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="a", skill_name="chip_a", sub_task="t", layer=0))

        executor = DAGExecutor(three_chip_registry)
        result = await executor.execute(dag, context)

        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_dag_result_layers_executed(self, three_chip_registry, context):
        """DAGResult tracks how many layers were executed."""
        dag = DAGBuilder.from_skill_sequence(
            ["chip_a", "chip_b", "chip_c"],
            three_chip_registry,
        )

        executor = DAGExecutor(three_chip_registry)
        result = await executor.execute(dag, context)

        assert result.layers_executed == 3

    def test_dag_result_dataclass_defaults(self):
        """DAGResult defaults are sensible."""
        result = DAGResult(dag_id="test")

        assert result.artifacts == {}
        assert result.node_results == {}
        assert result.node_errors == {}
        assert result.success is True
        assert result.execution_time_ms == 0.0
        assert result.layers_executed == 0
