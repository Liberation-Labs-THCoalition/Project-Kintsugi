"""EFE-Driven Scaffold Exploration — Phase 4.

Uses Expected Free Energy to decide whether the shadow fork should:
  1. EXPLORE: try a genuinely novel scaffold (high epistemic value)
  2. REFINE: try a variant of the best known scaffold (moderate epistemic)
  3. SKIP: don't bother with shadow comparison (low epistemic, high risk)

The EFE computation uses the scaffold KG to estimate:
  - Risk: probability that exploration fails (from loss rates)
  - Ambiguity: how uncertain the current best is (from comparison count)
  - Epistemic: information gain from a new comparison (inverse of experience)

Early in the system's life: high epistemic value (few comparisons,
much to learn). Later: pragmatic value dominates (patterns established,
exploration has diminishing returns). This naturally implements the
explore→exploit transition without manual scheduling.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum

from kintsugi.cognition.efe import EFECalculator, EFEWeights, EFEScore
from kintsugi.kintsugi_engine.scaffold_memory import InMemoryScaffoldKG

logger = logging.getLogger(__name__)


class ExplorationDecision(str, Enum):
    EXPLORE = "EXPLORE"    # Try a genuinely novel scaffold
    REFINE = "REFINE"      # Try a variant of the best known
    SKIP = "SKIP"          # Don't shadow-compare this time


@dataclass
class ExplorationContext:
    """Context for making an exploration decision."""
    task_type: str
    total_comparisons_for_type: int
    best_pattern_win_rate: float
    best_pattern_total: int
    patterns_seen: int
    recent_explore_wins: int = 0
    recent_explore_losses: int = 0


@dataclass
class ExplorationResult:
    """The exploration decision with rationale."""
    decision: ExplorationDecision
    efe_score: EFEScore
    rationale: str
    explore_budget_remaining: int = 0


class ScaffoldExplorer:
    """EFE-driven exploration decisions for scaffold evolution.

    Parameters
    ----------
    kg:
        The scaffold knowledge graph.
    min_comparisons_before_skip:
        Minimum comparisons for a task type before SKIP becomes possible.
        Below this, always explore.
    max_explore_per_session:
        Budget cap on shadow comparisons per session to prevent runaway.
    efe_weights:
        Weights for the EFE calculation. Default emphasizes epistemic
        early (when few comparisons exist) and risk later.
    """

    def __init__(
        self,
        kg: InMemoryScaffoldKG,
        min_comparisons_before_skip: int = 5,
        max_explore_per_session: int = 10,
        efe_weights: EFEWeights | None = None,
    ):
        self._kg = kg
        self._min_before_skip = min_comparisons_before_skip
        self._max_per_session = max_explore_per_session
        self._session_explores = 0
        self._efe = EFECalculator(
            default_weights=efe_weights or EFEWeights(
                risk=0.3, ambiguity=0.3, epistemic=0.4
            )
        )

    def decide(self, task_type: str) -> ExplorationResult:
        """Should we explore, refine, or skip for this task type?"""
        if self._session_explores >= self._max_per_session:
            return ExplorationResult(
                decision=ExplorationDecision.SKIP,
                efe_score=EFEScore(total=0, risk_component=0,
                                   ambiguity_component=0, epistemic_component=0,
                                   policy_id="skip_budget"),
                rationale=f"Session explore budget exhausted ({self._max_per_session})",
                explore_budget_remaining=0,
            )

        # Gather context from KG
        win_rates = self._kg.get_win_rates(task_type)
        preferred = self._kg.get_preferred_patterns(task_type)

        total_comparisons = sum(
            self._kg._wins.get((p, task_type), 0) +
            self._kg._losses.get((p, task_type), 0)
            for p in set(p for (p, tt) in self._kg._wins if tt == task_type) |
                       set(p for (p, tt) in self._kg._losses if tt == task_type)
        ) // 2  # each comparison counts once per winner and once per loser

        best_rate = max(win_rates.values()) if win_rates else 0.5
        patterns_seen = len(win_rates)

        # Compute EFE components
        risk = self._compute_risk(best_rate, total_comparisons)
        ambiguity = self._compute_ambiguity(total_comparisons, patterns_seen)
        information_gain = self._compute_epistemic(total_comparisons, patterns_seen)

        # EFE: lower = preferred. Exploration has negative epistemic (good)
        # but positive risk (bad). The balance determines the decision.
        efe = self._efe.calculate_efe(
            policy_id="explore",
            predicted_outcome={"scaffold_quality": 1.0 - risk},
            desired_outcome={"scaffold_quality": 1.0},
            uncertainty=ambiguity,
            information_gain=information_gain,
        )

        # Decision thresholds
        if total_comparisons < self._min_before_skip:
            decision = ExplorationDecision.EXPLORE
            rationale = (
                f"Early phase: only {total_comparisons} comparisons for "
                f"'{task_type}'. Exploring to build knowledge."
            )
        elif efe.epistemic_component < -0.15:
            decision = ExplorationDecision.EXPLORE
            rationale = (
                f"High epistemic value ({information_gain:.2f}): "
                f"novel scaffolds likely to teach something."
            )
        elif efe.epistemic_component < -0.05:
            decision = ExplorationDecision.REFINE
            rationale = (
                f"Moderate epistemic value: refine best pattern "
                f"'{preferred[0] if preferred else '?'}' "
                f"(win rate {best_rate:.0%}, {total_comparisons} comparisons)."
            )
        else:
            decision = ExplorationDecision.SKIP
            rationale = (
                f"Low epistemic value: '{preferred[0] if preferred else '?'}' "
                f"is well-established (win rate {best_rate:.0%}, "
                f"{total_comparisons} comparisons). Skip shadow comparison."
            )

        if decision in (ExplorationDecision.EXPLORE, ExplorationDecision.REFINE):
            self._session_explores += 1

        return ExplorationResult(
            decision=decision,
            efe_score=efe,
            rationale=rationale,
            explore_budget_remaining=self._max_per_session - self._session_explores,
        )

    def _compute_risk(self, best_win_rate: float, total: int) -> float:
        """Risk of exploration: how likely is the explore scaffold to fail?

        High when the best known pattern is already very good (little room
        for improvement, exploration is "wasted"). Low when the best pattern
        is mediocre (exploration has upside).
        """
        if total == 0:
            return 0.2  # Unknown risk — moderate, don't prevent exploration
        return best_win_rate * 0.5  # Higher best rate → higher risk of exploration being worse

    def _compute_ambiguity(self, total: int, patterns_seen: int) -> float:
        """Ambiguity: how uncertain is our current best estimate?

        High when few comparisons exist. Decays with experience.
        """
        if total == 0:
            return 1.0
        return 1.0 / (1.0 + math.log1p(total))

    def _compute_epistemic(self, total: int, patterns_seen: int) -> float:
        """Epistemic value: how much would a new comparison teach us?

        High when few patterns have been tried. Decays as diversity saturates.
        Exploration of a NEW pattern type has more value than another comparison
        of already-seen patterns.
        """
        if total == 0:
            return 1.0
        diversity_bonus = 0.2 if patterns_seen < 4 else 0.0
        base = 1.0 / (1.0 + total * 0.5)
        return base + diversity_bonus

    def reset_session(self) -> None:
        """Reset session explore counter (call at session start)."""
        self._session_explores = 0
