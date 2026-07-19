"""Tests for ScaffoldComparator — exploit vs explore scaffold comparison.

Covers:
  - ScaffoldMetrics and ScaffoldComparison dataclass defaults
  - ScaffoldComparator default and custom weights
  - extract_metrics() with various DAGResult shapes
  - compare() across all scoring dimensions and winner outcomes
  - _make_recommendation() message classification
"""

from __future__ import annotations

import pytest

from kintsugi.skills.dag import DAGNode, DAGResult, SkillDAG
from kintsugi.skills.base import SkillResponse
from kintsugi.kintsugi_engine.scaffold_generator import ScaffoldProposal
from kintsugi.kintsugi_engine.scaffold_comparator import (
    ScaffoldComparator,
    ScaffoldComparison,
    ScaffoldMetrics,
)


# ---------------------------------------------------------------------------
# Helpers — build lightweight mock objects
# ---------------------------------------------------------------------------

def _make_dag(*node_ids: str, dag_id: str = "dag-test") -> SkillDAG:
    """Build a minimal SkillDAG with the given node IDs (single layer)."""
    dag = SkillDAG(dag_id=dag_id)
    for i, nid in enumerate(node_ids):
        dag.add_node(DAGNode(
            node_id=nid,
            skill_name="stub",
            sub_task="stub",
            layer=0,
        ))
    return dag


def _make_proposal(
    node_ids: list[str],
    strategy: str = "exploit",
    source: str = "generated",
    dag_id: str = "dag-test",
) -> ScaffoldProposal:
    dag = _make_dag(*node_ids, dag_id=dag_id)
    return ScaffoldProposal(
        dag=dag,
        strategy=strategy,
        rationale="test",
        source=source,
    )


def _make_result(
    dag_id: str = "dag-test",
    success: bool = True,
    execution_time_ms: float = 100.0,
    layers_executed: int = 1,
    succeeded_nodes: list[str] | None = None,
    failed_nodes: dict[str, str] | None = None,
    artifacts: dict | None = None,
) -> DAGResult:
    """Build a DAGResult with fine-grained control over node outcomes."""
    node_results = {}
    for nid in (succeeded_nodes or []):
        node_results[nid] = SkillResponse(content="ok", success=True)

    return DAGResult(
        dag_id=dag_id,
        artifacts=artifacts or {},
        node_results=node_results,
        node_errors=failed_nodes or {},
        success=success,
        execution_time_ms=execution_time_ms,
        layers_executed=layers_executed,
    )


# ===================================================================
# 1. Dataclass defaults
# ===================================================================

class TestScaffoldMetricsDefaults:
    def test_defaults(self):
        m = ScaffoldMetrics(dag_id="d", strategy="s", source="src")
        assert m.completed is True
        assert m.execution_time_ms == 0.0
        assert m.layers_executed == 0
        assert m.nodes_succeeded == 0
        assert m.nodes_failed == 0
        assert m.total_nodes == 0
        assert m.output_quality == 0.0
        assert m.gate_passed is False
        assert m.confidence_grade == "LOW"
        assert m.error_messages == []

    def test_error_messages_independent(self):
        """Each instance should get its own list."""
        m1 = ScaffoldMetrics(dag_id="d1", strategy="s", source="src")
        m2 = ScaffoldMetrics(dag_id="d2", strategy="s", source="src")
        m1.error_messages.append("oops")
        assert m2.error_messages == []


class TestScaffoldComparisonDefaults:
    def test_defaults(self):
        c = ScaffoldComparison(task="t", winner="tie", margin=0.0)
        assert c.exploit_metrics is None
        assert c.explore_metrics is None
        assert c.dimensions == {}
        assert c.recommendation == ""
        assert c.timestamp == ""

    def test_dimensions_independent(self):
        c1 = ScaffoldComparison(task="t1", winner="tie", margin=0.0)
        c2 = ScaffoldComparison(task="t2", winner="tie", margin=0.0)
        c1.dimensions["x"] = "y"
        assert c2.dimensions == {}


# ===================================================================
# 2. ScaffoldComparator weights
# ===================================================================

class TestComparatorWeights:
    def test_default_weights_sum_to_one(self):
        comp = ScaffoldComparator()
        assert abs(sum(comp._weights.values()) - 1.0) < 1e-9

    def test_default_weight_keys(self):
        comp = ScaffoldComparator()
        assert set(comp._weights) == {"completion", "efficiency", "quality", "robustness"}

    def test_default_weight_values(self):
        comp = ScaffoldComparator()
        assert comp._weights["completion"] == 0.30
        assert comp._weights["efficiency"] == 0.15
        assert comp._weights["quality"] == 0.40
        assert comp._weights["robustness"] == 0.15

    def test_custom_weights(self):
        w = {"completion": 0.5, "efficiency": 0.1, "quality": 0.3, "robustness": 0.1}
        comp = ScaffoldComparator(weights=w)
        assert comp._weights == w

    def test_custom_weights_do_not_mutate_defaults(self):
        w = {"completion": 0.5, "efficiency": 0.1, "quality": 0.3, "robustness": 0.1}
        ScaffoldComparator(weights=w)
        # Defaults should remain unchanged
        comp2 = ScaffoldComparator()
        assert comp2._weights["completion"] == 0.30


# ===================================================================
# 3. extract_metrics()
# ===================================================================

class TestExtractMetrics:
    def setup_method(self):
        self.comp = ScaffoldComparator()

    def test_counts_succeeded_and_failed(self):
        proposal = _make_proposal(["a", "b", "c"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a", "b"],
            failed_nodes={"c": "timeout"},
            success=False,
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.nodes_succeeded == 2
        assert m.nodes_failed == 1
        assert m.total_nodes == 3

    def test_all_nodes_succeeded(self):
        proposal = _make_proposal(["x", "y"], strategy="explore")
        result = _make_result(succeeded_nodes=["x", "y"], success=True)
        m = self.comp.extract_metrics(proposal, result)
        assert m.nodes_succeeded == 2
        assert m.nodes_failed == 0
        assert m.completed is True

    def test_no_nodes(self):
        proposal = _make_proposal([], strategy="exploit")
        result = _make_result(success=True)
        m = self.comp.extract_metrics(proposal, result)
        assert m.total_nodes == 0
        assert m.nodes_succeeded == 0
        assert m.nodes_failed == 0

    # --- gate_result handling ---

    def test_gate_result_dict_with_passed_and_confidence(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "HIGH"}},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.gate_passed is True
        assert m.confidence_grade == "HIGH"
        assert m.output_quality == 0.9

    def test_gate_result_dict_medium_confidence(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "MEDIUM"}},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.confidence_grade == "MEDIUM"
        assert m.output_quality == 0.6

    def test_gate_result_dict_low_confidence(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": False, "confidence": "LOW"}},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.gate_passed is False
        assert m.confidence_grade == "LOW"
        assert m.output_quality == 0.3

    def test_gate_result_dict_unknown_confidence_defaults_to_low(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "UNKNOWN"}},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.output_quality == 0.3

    def test_gate_result_plain_bool_true(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": True},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.gate_passed is True
        assert m.confidence_grade == "LOW"
        assert m.output_quality == 0.3

    def test_gate_result_plain_bool_false(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": False},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.gate_passed is False

    def test_gate_result_truthy_string(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(
            succeeded_nodes=["a"],
            artifacts={"final": "success"},
        )
        m = self.comp.extract_metrics(proposal, result)
        assert m.gate_passed is True
        assert m.confidence_grade == "LOW"

    def test_gate_result_empty_dict_no_final(self):
        """No 'final' key in artifacts -> gate defaults to not passed."""
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(succeeded_nodes=["a"], artifacts={})
        m = self.comp.extract_metrics(proposal, result)
        assert m.gate_passed is False
        assert m.confidence_grade == "LOW"
        assert m.output_quality == 0.3

    # --- metadata passthrough ---

    def test_strategy_and_source_passed_through(self):
        proposal = _make_proposal(
            ["a"], strategy="my_strat", source="manual", dag_id="d42"
        )
        result = _make_result(dag_id="d42")
        m = self.comp.extract_metrics(proposal, result)
        assert m.dag_id == "d42"
        assert m.strategy == "my_strat"
        assert m.source == "manual"

    def test_execution_time_and_layers(self):
        proposal = _make_proposal(["a"], strategy="exploit")
        result = _make_result(execution_time_ms=1234.5, layers_executed=3)
        m = self.comp.extract_metrics(proposal, result)
        assert m.execution_time_ms == 1234.5
        assert m.layers_executed == 3

    def test_error_messages_collected(self):
        proposal = _make_proposal(["a", "b"], strategy="exploit")
        result = _make_result(
            failed_nodes={"a": "boom", "b": "crash"},
            success=False,
        )
        m = self.comp.extract_metrics(proposal, result)
        assert set(m.error_messages) == {"boom", "crash"}


# ===================================================================
# 4. compare() — winner determination
# ===================================================================

class TestCompareWinner:
    """Test the overall compare() method for winner/margin logic."""

    def setup_method(self):
        self.comp = ScaffoldComparator()

    def _quick_compare(
        self,
        exploit_kwargs: dict,
        explore_kwargs: dict,
        exploit_nodes: list[str] | None = None,
        explore_nodes: list[str] | None = None,
    ) -> ScaffoldComparison:
        """Shorthand: build proposals/results and compare."""
        e_nodes = exploit_nodes or ["a"]
        x_nodes = explore_nodes or ["a"]
        exploit_p = _make_proposal(e_nodes, strategy="exploit", dag_id="exploit-dag")
        explore_p = _make_proposal(x_nodes, strategy="explore", dag_id="explore-dag")
        exploit_r = _make_result(dag_id="exploit-dag", **exploit_kwargs)
        explore_r = _make_result(dag_id="explore-dag", **explore_kwargs)
        return self.comp.compare("test-task", exploit_p, exploit_r, explore_p, explore_r)

    def test_exploit_wins_decisively(self):
        """Exploit: completed, high quality.  Explore: failed, low quality."""
        c = self._quick_compare(
            exploit_kwargs=dict(
                success=True, execution_time_ms=50,
                succeeded_nodes=["a"],
                artifacts={"final": {"passed": True, "confidence": "HIGH"}},
            ),
            explore_kwargs=dict(
                success=False, execution_time_ms=200,
                failed_nodes={"a": "err"},
                artifacts={"final": {"passed": False, "confidence": "LOW"}},
            ),
        )
        assert c.winner == "exploit"
        assert c.margin > 0.05

    def test_explore_wins(self):
        """Explore: completed, high quality.  Exploit: failed, low quality."""
        c = self._quick_compare(
            exploit_kwargs=dict(
                success=False, execution_time_ms=200,
                failed_nodes={"a": "err"},
                artifacts={"final": {"passed": False, "confidence": "LOW"}},
            ),
            explore_kwargs=dict(
                success=True, execution_time_ms=50,
                succeeded_nodes=["a"],
                artifacts={"final": {"passed": True, "confidence": "HIGH"}},
            ),
        )
        assert c.winner == "explore"
        assert c.margin > 0.05

    def test_tie_when_identical(self):
        """Identical outcomes -> tie with margin 0.0."""
        same = dict(
            success=True, execution_time_ms=100,
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "MEDIUM"}},
        )
        c = self._quick_compare(exploit_kwargs=same, explore_kwargs=same)
        assert c.winner == "tie"
        assert c.margin == 0.0

    def test_close_result_is_tie(self):
        """Very small difference (<0.05) treated as tie."""
        c = self._quick_compare(
            exploit_kwargs=dict(
                success=True, execution_time_ms=100,
                succeeded_nodes=["a"],
                artifacts={"final": {"passed": True, "confidence": "MEDIUM"}},
            ),
            explore_kwargs=dict(
                success=True, execution_time_ms=105,
                succeeded_nodes=["a"],
                artifacts={"final": {"passed": True, "confidence": "MEDIUM"}},
            ),
        )
        assert c.winner == "tie"
        assert c.margin == 0.0

    def test_comparison_has_timestamp(self):
        same = dict(success=True, execution_time_ms=100, succeeded_nodes=["a"])
        c = self._quick_compare(exploit_kwargs=same, explore_kwargs=same)
        assert c.timestamp != ""

    def test_comparison_has_task(self):
        same = dict(success=True, execution_time_ms=100, succeeded_nodes=["a"])
        c = self._quick_compare(exploit_kwargs=same, explore_kwargs=same)
        assert c.task == "test-task"

    def test_margin_is_rounded(self):
        """Margin should have at most 3 decimal places."""
        c = self._quick_compare(
            exploit_kwargs=dict(
                success=True, execution_time_ms=50,
                succeeded_nodes=["a"],
                artifacts={"final": {"passed": True, "confidence": "HIGH"}},
            ),
            explore_kwargs=dict(
                success=False, execution_time_ms=200,
                failed_nodes={"a": "err"},
                artifacts={"final": {"passed": False, "confidence": "LOW"}},
            ),
        )
        # Margin text representation should have <= 3 decimal digits
        assert c.margin == round(c.margin, 3)


# ===================================================================
# 5. compare() — individual scoring dimensions
# ===================================================================

class TestCompareDimensions:
    """Test that each scoring dimension functions correctly."""

    def test_completion_dimension(self):
        """Completed scaffold scores 1.0 on completion; failed scores 0.0."""
        comp = ScaffoldComparator(weights={
            "completion": 1.0, "efficiency": 0.0, "quality": 0.0, "robustness": 0.0
        })
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", success=True, succeeded_nodes=["a"])
        explore_r = _make_result(dag_id="e2", success=False, failed_nodes={"a": "err"})
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "exploit"
        assert "completion" in c.dimensions

    def test_efficiency_dimension_faster_wins(self):
        """Faster scaffold gets a higher efficiency score."""
        comp = ScaffoldComparator(weights={
            "completion": 0.0, "efficiency": 1.0, "quality": 0.0, "robustness": 0.0
        })
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        # Exploit is faster
        exploit_r = _make_result(dag_id="e1", success=True, execution_time_ms=50,
                                 succeeded_nodes=["a"])
        explore_r = _make_result(dag_id="e2", success=True, execution_time_ms=200,
                                 succeeded_nodes=["a"])
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "exploit"
        assert "efficiency" in c.dimensions

    def test_efficiency_dimension_equal_time_is_tie(self):
        """Same execution time -> tie on efficiency."""
        comp = ScaffoldComparator(weights={
            "completion": 0.0, "efficiency": 1.0, "quality": 0.0, "robustness": 0.0
        })
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", success=True, execution_time_ms=100,
                                 succeeded_nodes=["a"])
        explore_r = _make_result(dag_id="e2", success=True, execution_time_ms=100,
                                 succeeded_nodes=["a"])
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "tie"

    def test_quality_dimension_high_vs_low(self):
        """Higher confidence grade -> higher quality score."""
        comp = ScaffoldComparator(weights={
            "completion": 0.0, "efficiency": 0.0, "quality": 1.0, "robustness": 0.0
        })
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        exploit_r = _make_result(
            dag_id="e1", success=True, succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "HIGH"}},
        )
        explore_r = _make_result(
            dag_id="e2", success=True, succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "LOW"}},
        )
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "exploit"
        # Quality difference: 0.9 - 0.3 = 0.6 (weight=1.0)
        assert c.margin == pytest.approx(0.6, abs=0.01)

    def test_robustness_dimension_fewer_errors_wins(self):
        """Scaffold with fewer node errors gets a higher robustness score."""
        comp = ScaffoldComparator(weights={
            "completion": 0.0, "efficiency": 0.0, "quality": 0.0, "robustness": 1.0
        })
        exploit_p = _make_proposal(["a", "b", "c", "d"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a", "b", "c", "d"], strategy="explore", dag_id="e2")
        # Exploit: 0 errors -> robustness = 1.0
        exploit_r = _make_result(
            dag_id="e1", success=True,
            succeeded_nodes=["a", "b", "c", "d"],
        )
        # Explore: 2 errors out of 4 -> robustness = 0.5
        explore_r = _make_result(
            dag_id="e2", success=False,
            succeeded_nodes=["a", "b"],
            failed_nodes={"c": "err1", "d": "err2"},
        )
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "exploit"
        assert c.margin == pytest.approx(0.5, abs=0.01)

    def test_robustness_zero_nodes_safe(self):
        """Zero total nodes should not cause ZeroDivisionError."""
        comp = ScaffoldComparator(weights={
            "completion": 0.0, "efficiency": 0.0, "quality": 0.0, "robustness": 1.0
        })
        exploit_p = _make_proposal([], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal([], strategy="explore", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", success=True)
        explore_r = _make_result(dag_id="e2", success=True)
        # Should not raise
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "tie"

    def test_efficiency_both_zero_time_safe(self):
        """Both scaffolds with 0ms execution should not divide by zero."""
        comp = ScaffoldComparator(weights={
            "completion": 0.0, "efficiency": 1.0, "quality": 0.0, "robustness": 0.0
        })
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", execution_time_ms=0.0, succeeded_nodes=["a"])
        explore_r = _make_result(dag_id="e2", execution_time_ms=0.0, succeeded_nodes=["a"])
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "tie"

    def test_dimensions_dict_populated(self):
        """All four dimension keys should appear in the output."""
        comp = ScaffoldComparator()
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", success=True, succeeded_nodes=["a"])
        explore_r = _make_result(dag_id="e2", success=True, succeeded_nodes=["a"])
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert set(c.dimensions) == {"completion", "efficiency", "quality", "robustness"}

    def test_metrics_attached_to_comparison(self):
        """exploit_metrics and explore_metrics should be populated."""
        comp = ScaffoldComparator()
        exploit_p = _make_proposal(["a"], strategy="exploit", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="explore", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", success=True, succeeded_nodes=["a"])
        explore_r = _make_result(dag_id="e2", success=True, succeeded_nodes=["a"])
        c = comp.compare("t", exploit_p, exploit_r, explore_p, explore_r)
        assert c.exploit_metrics is not None
        assert c.explore_metrics is not None
        assert c.exploit_metrics.strategy == "exploit"
        assert c.explore_metrics.strategy == "explore"


# ===================================================================
# 6. _make_recommendation()
# ===================================================================

class TestMakeRecommendation:
    def setup_method(self):
        self.comp = ScaffoldComparator()
        self.exploit_m = ScaffoldMetrics(
            dag_id="e1", strategy="baseline", source="gen"
        )
        self.explore_m = ScaffoldMetrics(
            dag_id="e2", strategy="novel", source="gen"
        )

    def test_tie_recommendation(self):
        rec = self.comp._make_recommendation("tie", 0.0, self.exploit_m, self.explore_m)
        assert "No clear winner" in rec

    def test_explore_wins_large_margin_promote(self):
        rec = self.comp._make_recommendation("explore", 0.20, self.exploit_m, self.explore_m)
        assert "PROMOTE" in rec
        assert "novel" in rec  # winner strategy name
        assert "baseline" in rec  # loser strategy name
        assert "0.20" in rec

    def test_explore_wins_at_threshold_promote(self):
        """Margin exactly > 0.15 triggers PROMOTE."""
        rec = self.comp._make_recommendation("explore", 0.16, self.exploit_m, self.explore_m)
        assert "PROMOTE" in rec

    def test_explore_wins_small_margin_promising(self):
        rec = self.comp._make_recommendation("explore", 0.10, self.exploit_m, self.explore_m)
        assert "PROMISING" in rec
        assert "threshold: 3 wins" in rec

    def test_explore_wins_at_boundary_promising(self):
        """Margin exactly 0.15 triggers PROMISING (not PROMOTE)."""
        rec = self.comp._make_recommendation("explore", 0.15, self.exploit_m, self.explore_m)
        assert "PROMISING" in rec

    def test_exploit_wins_hold(self):
        rec = self.comp._make_recommendation("exploit", 0.12, self.exploit_m, self.explore_m)
        assert "HOLD" in rec
        assert "baseline" in rec  # exploit strategy name
        assert "0.12" in rec

    def test_recommendation_via_compare_explore_promote(self):
        """End-to-end: explore wins decisively -> PROMOTE recommendation."""
        comp = ScaffoldComparator()
        exploit_p = _make_proposal(["a"], strategy="old_strat", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="new_strat", dag_id="e2")
        exploit_r = _make_result(
            dag_id="e1", success=False, execution_time_ms=500,
            failed_nodes={"a": "crash"},
            artifacts={"final": {"passed": False, "confidence": "LOW"}},
        )
        explore_r = _make_result(
            dag_id="e2", success=True, execution_time_ms=50,
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "HIGH"}},
        )
        c = comp.compare("task", exploit_p, exploit_r, explore_p, explore_r)
        assert c.winner == "explore"
        assert "PROMOTE" in c.recommendation

    def test_recommendation_via_compare_tie(self):
        """End-to-end: identical outcomes -> tie -> 'No clear winner'."""
        comp = ScaffoldComparator()
        same_kwargs = dict(
            success=True, execution_time_ms=100,
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "MEDIUM"}},
        )
        exploit_p = _make_proposal(["a"], strategy="s1", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="s2", dag_id="e2")
        exploit_r = _make_result(dag_id="e1", **same_kwargs)
        explore_r = _make_result(dag_id="e2", **same_kwargs)
        c = comp.compare("task", exploit_p, exploit_r, explore_p, explore_r)
        assert "No clear winner" in c.recommendation

    def test_recommendation_via_compare_exploit_hold(self):
        """End-to-end: exploit wins -> HOLD."""
        comp = ScaffoldComparator()
        exploit_p = _make_proposal(["a"], strategy="proven", dag_id="e1")
        explore_p = _make_proposal(["a"], strategy="risky", dag_id="e2")
        exploit_r = _make_result(
            dag_id="e1", success=True, execution_time_ms=50,
            succeeded_nodes=["a"],
            artifacts={"final": {"passed": True, "confidence": "HIGH"}},
        )
        explore_r = _make_result(
            dag_id="e2", success=False, execution_time_ms=500,
            failed_nodes={"a": "err"},
            artifacts={"final": {"passed": False, "confidence": "LOW"}},
        )
        c = comp.compare("task", exploit_p, exploit_r, explore_p, explore_r)
        assert "HOLD" in c.recommendation
