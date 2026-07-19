"""Scaffold Comparator — evaluate exploit vs explore scaffold outcomes.

Phase 2 of Adaptive Scaffold Evolution. Extends the shadow fork workflow
to compare two scaffold strategies on the same task and record which one
produced better results.

Flow:
  1. ScaffoldGenerator.generate_pair() → exploit DAG + explore DAG
  2. DAGExecutor runs both (primary=exploit, shadow fork=explore)
  3. ScaffoldComparator.compare() → winner + metrics
  4. (Phase 3) KG records the comparison for future recall

The comparator doesn't decide what's "better" in absolute terms —
it compares two scaffold outcomes on task-specific metrics and reports
which one performed better, by how much, and on which dimensions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from kintsugi.skills.dag import DAGResult, SkillDAG
from kintsugi.kintsugi_engine.scaffold_generator import ScaffoldProposal

logger = logging.getLogger(__name__)


@dataclass
class ScaffoldMetrics:
    """Measured performance of a scaffold execution."""
    dag_id: str
    strategy: str
    source: str

    completed: bool = True
    execution_time_ms: float = 0.0
    layers_executed: int = 0
    nodes_succeeded: int = 0
    nodes_failed: int = 0
    total_nodes: int = 0

    output_quality: float = 0.0
    gate_passed: bool = False
    confidence_grade: str = "LOW"

    error_messages: list[str] = field(default_factory=list)


@dataclass
class ScaffoldComparison:
    """Result of comparing two scaffold executions."""
    task: str
    winner: str  # "exploit" | "explore" | "tie"
    margin: float  # 0.0 (tie) to 1.0 (decisive)

    exploit_metrics: ScaffoldMetrics | None = None
    explore_metrics: ScaffoldMetrics | None = None

    dimensions: dict[str, str] = field(default_factory=dict)
    recommendation: str = ""
    timestamp: str = ""


class ScaffoldComparator:
    """Compare scaffold execution outcomes.

    Scoring dimensions (each 0-1, weighted):
      - completion: did the DAG complete without errors?
      - efficiency: execution time relative to the other
      - quality: output quality from the gate or judge
      - robustness: error count and recovery

    Parameters
    ----------
    weights:
        Dict of dimension weights. Must sum to 1.0.
        Default: balanced across all dimensions.
    """

    DEFAULT_WEIGHTS = {
        "completion": 0.30,
        "efficiency": 0.15,
        "quality": 0.40,
        "robustness": 0.15,
    }

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)

    def extract_metrics(
        self,
        proposal: ScaffoldProposal,
        result: DAGResult,
    ) -> ScaffoldMetrics:
        """Extract metrics from a scaffold execution result."""
        total = len(proposal.dag.nodes)
        succeeded = sum(
            1 for nid in proposal.dag.nodes
            if nid in result.node_results and result.node_results[nid].success
        )
        failed = sum(
            1 for nid in proposal.dag.nodes
            if nid in result.node_errors
        )

        gate_result = result.artifacts.get("final", {})
        gate_passed = gate_result.get("passed", False) if isinstance(gate_result, dict) else bool(gate_result)
        confidence = gate_result.get("confidence", "LOW") if isinstance(gate_result, dict) else "LOW"
        quality = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}.get(confidence, 0.3)

        return ScaffoldMetrics(
            dag_id=proposal.dag.dag_id,
            strategy=proposal.strategy,
            source=proposal.source,
            completed=result.success,
            execution_time_ms=result.execution_time_ms,
            layers_executed=result.layers_executed,
            nodes_succeeded=succeeded,
            nodes_failed=failed,
            total_nodes=total,
            output_quality=quality,
            gate_passed=gate_passed,
            confidence_grade=confidence,
            error_messages=list(result.node_errors.values()),
        )

    def compare(
        self,
        task: str,
        exploit_proposal: ScaffoldProposal,
        exploit_result: DAGResult,
        explore_proposal: ScaffoldProposal,
        explore_result: DAGResult,
    ) -> ScaffoldComparison:
        """Compare exploit vs explore scaffold outcomes."""
        exploit_m = self.extract_metrics(exploit_proposal, exploit_result)
        explore_m = self.extract_metrics(explore_proposal, explore_result)

        scores = {"exploit": 0.0, "explore": 0.0}
        dimensions = {}

        # Completion: binary, completed = 1.0
        e1_comp = 1.0 if exploit_m.completed else 0.0
        e2_comp = 1.0 if explore_m.completed else 0.0
        scores["exploit"] += self._weights["completion"] * e1_comp
        scores["explore"] += self._weights["completion"] * e2_comp
        dimensions["completion"] = f"exploit={e1_comp:.1f} explore={e2_comp:.1f}"

        # Efficiency: faster = better (normalized)
        max_time = max(exploit_m.execution_time_ms, explore_m.execution_time_ms, 1)
        e1_eff = 1.0 - (exploit_m.execution_time_ms / max_time)
        e2_eff = 1.0 - (explore_m.execution_time_ms / max_time)
        scores["exploit"] += self._weights["efficiency"] * e1_eff
        scores["explore"] += self._weights["efficiency"] * e2_eff
        dimensions["efficiency"] = f"exploit={exploit_m.execution_time_ms:.0f}ms explore={explore_m.execution_time_ms:.0f}ms"

        # Quality: from gate/judge
        scores["exploit"] += self._weights["quality"] * exploit_m.output_quality
        scores["explore"] += self._weights["quality"] * explore_m.output_quality
        dimensions["quality"] = f"exploit={exploit_m.confidence_grade} explore={explore_m.confidence_grade}"

        # Robustness: fewer errors = better
        e1_rob = 1.0 - (exploit_m.nodes_failed / max(exploit_m.total_nodes, 1))
        e2_rob = 1.0 - (explore_m.nodes_failed / max(explore_m.total_nodes, 1))
        scores["exploit"] += self._weights["robustness"] * e1_rob
        scores["explore"] += self._weights["robustness"] * e2_rob
        dimensions["robustness"] = f"exploit={exploit_m.nodes_failed} errors explore={explore_m.nodes_failed} errors"

        # Determine winner
        diff = scores["exploit"] - scores["explore"]
        if abs(diff) < 0.05:
            winner = "tie"
            margin = 0.0
        elif diff > 0:
            winner = "exploit"
            margin = diff
        else:
            winner = "explore"
            margin = -diff

        recommendation = self._make_recommendation(winner, margin, exploit_m, explore_m)

        return ScaffoldComparison(
            task=task,
            winner=winner,
            margin=round(margin, 3),
            exploit_metrics=exploit_m,
            explore_metrics=explore_m,
            dimensions=dimensions,
            recommendation=recommendation,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

    def _make_recommendation(
        self, winner: str, margin: float,
        exploit_m: ScaffoldMetrics, explore_m: ScaffoldMetrics
    ) -> str:
        """Generate a human-readable recommendation."""
        if winner == "tie":
            return "No clear winner. Keep current exploit scaffold."

        winner_m = exploit_m if winner == "exploit" else explore_m
        loser_m = explore_m if winner == "exploit" else exploit_m

        if winner == "explore" and margin > 0.15:
            return (
                f"PROMOTE: explore scaffold ({winner_m.strategy}) "
                f"outperformed exploit ({loser_m.strategy}) by {margin:.2f}. "
                f"Consider adopting as new default for this task type."
            )
        elif winner == "explore":
            return (
                f"PROMISING: explore scaffold ({winner_m.strategy}) "
                f"edged exploit ({loser_m.strategy}) by {margin:.2f}. "
                f"Needs more comparisons before promotion (threshold: 3 wins)."
            )
        else:
            return (
                f"HOLD: exploit scaffold ({winner_m.strategy}) "
                f"won by {margin:.2f}. Current strategy confirmed."
            )


# ---------------------------------------------------------------------------
# Integration helper: run the full scaffold comparison loop
# ---------------------------------------------------------------------------

async def run_scaffold_comparison(
    task: str,
    generator,  # ScaffoldGenerator
    executor,   # DAGExecutor
    context,    # SkillContext
    comparator: ScaffoldComparator | None = None,
    initial_artifacts: dict | None = None,
) -> ScaffoldComparison:
    """Full loop: generate pair → execute both → compare → return.

    This is the integration point that wires Phase 1 (generator) into
    Phase 2 (comparison). Phase 3 will add KG recording of the result.
    """
    comparator = comparator or ScaffoldComparator()

    # Generate exploit + explore scaffolds
    exploit_proposal, explore_proposal = generator.generate_pair(task)

    # Execute both DAGs
    exploit_result = await executor.execute(
        exploit_proposal.dag, context,
        initial_artifacts=initial_artifacts or {"question": task},
    )
    explore_result = await executor.execute(
        explore_proposal.dag, context,
        initial_artifacts=initial_artifacts or {"question": task},
    )

    # Compare outcomes
    comparison = comparator.compare(
        task, exploit_proposal, exploit_result,
        explore_proposal, explore_result,
    )

    logger.info(
        "Scaffold comparison: %s wins (margin %.3f) — %s",
        comparison.winner, comparison.margin, comparison.recommendation,
    )

    return comparison
