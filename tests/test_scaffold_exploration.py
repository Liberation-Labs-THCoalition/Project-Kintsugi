"""Tests for kintsugi.kintsugi_engine.scaffold_exploration."""

from __future__ import annotations

import math

import pytest

from kintsugi.cognition.efe import EFECalculator, EFEWeights, EFEScore
from kintsugi.kintsugi_engine.scaffold_exploration import (
    ExplorationDecision,
    ExplorationContext,
    ExplorationResult,
    ScaffoldExplorer,
)
from kintsugi.kintsugi_engine.scaffold_memory import InMemoryScaffoldKG
from kintsugi.kintsugi_engine.scaffold_comparator import ScaffoldComparison
from kintsugi.kintsugi_engine.scaffold_generator import ScaffoldProposal
from kintsugi.skills.dag import DAGNode, SkillDAG


# ---------------------------------------------------------------------------
# Helpers — same mock helpers as scaffold_memory tests
# ---------------------------------------------------------------------------


def _make_dag(strategy: str, nodes: list[tuple[str, int]]) -> SkillDAG:
    dag = SkillDAG(strategy=strategy)
    for skill_name, layer in nodes:
        node = DAGNode(
            node_id=f"{skill_name}_0",
            skill_name=skill_name,
            sub_task="test",
            layer=layer,
        )
        dag.add_node(node)
    return dag


def _make_proposal(strategy: str, skills: list[tuple[str, int]]) -> ScaffoldProposal:
    return ScaffoldProposal(
        dag=_make_dag(strategy, skills),
        strategy=strategy,
        rationale="test",
        source="test",
    )


def _make_comparison(winner: str, margin: float = 0.1,
                     timestamp: str = "2026-06-01T00:00:00") -> ScaffoldComparison:
    return ScaffoldComparison(
        task="test_task",
        winner=winner,
        margin=margin,
        timestamp=timestamp,
    )


EXPLOIT_SKILLS = [("code_analysis", 0), ("synthesis", 1)]
EXPLORE_SKILLS = [("security_review", 0), ("synthesis", 1)]


def _record_one(kg: InMemoryScaffoldKG, winner: str, task_type: str = "migration",
                exploit_strategy: str = "quality",
                explore_strategy: str = "efficiency",
                margin: float = 0.1) -> None:
    exploit = _make_proposal(exploit_strategy, EXPLOIT_SKILLS)
    explore = _make_proposal(explore_strategy, EXPLORE_SKILLS)
    comp = _make_comparison(winner, margin=margin)
    kg.record_comparison(comp, task_type, exploit, explore)


def _build_kg_with_comparisons(
    n: int,
    winner: str = "exploit",
    task_type: str = "migration",
) -> InMemoryScaffoldKG:
    """Build a KG pre-loaded with n comparisons."""
    kg = InMemoryScaffoldKG()
    for _ in range(n):
        _record_one(kg, winner, task_type=task_type)
    return kg


# ---------------------------------------------------------------------------
# ExplorationDecision enum
# ---------------------------------------------------------------------------


class TestExplorationDecision:
    def test_enum_values(self):
        assert ExplorationDecision.EXPLORE.value == "EXPLORE"
        assert ExplorationDecision.REFINE.value == "REFINE"
        assert ExplorationDecision.SKIP.value == "SKIP"

    def test_is_string_enum(self):
        assert isinstance(ExplorationDecision.EXPLORE, str)
        assert ExplorationDecision.EXPLORE == "EXPLORE"


# ---------------------------------------------------------------------------
# ScaffoldExplorer — empty KG
# ---------------------------------------------------------------------------


class TestExplorerEmptyKG:
    def test_always_explore_with_zero_comparisons(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        result = explorer.decide("migration")
        assert result.decision == ExplorationDecision.EXPLORE
        assert "Early phase" in result.rationale or "0 comparisons" in result.rationale


# ---------------------------------------------------------------------------
# ScaffoldExplorer — few comparisons (below min_comparisons_before_skip)
# ---------------------------------------------------------------------------


class TestExplorerFewComparisons:
    def test_explore_when_below_threshold(self):
        kg = _build_kg_with_comparisons(2)
        explorer = ScaffoldExplorer(kg, min_comparisons_before_skip=5)

        result = explorer.decide("migration")
        assert result.decision == ExplorationDecision.EXPLORE

    def test_explore_at_boundary_minus_one(self):
        kg = _build_kg_with_comparisons(4)
        explorer = ScaffoldExplorer(kg, min_comparisons_before_skip=5)

        result = explorer.decide("migration")
        assert result.decision == ExplorationDecision.EXPLORE


# ---------------------------------------------------------------------------
# ScaffoldExplorer — moderate data (REFINE zone)
# ---------------------------------------------------------------------------


class TestExplorerModerateData:
    def test_refine_with_moderate_comparisons(self):
        """With enough data that SKIP threshold is met but epistemic value
        is still moderate, expect REFINE."""
        kg = _build_kg_with_comparisons(6)
        explorer = ScaffoldExplorer(kg, min_comparisons_before_skip=5)

        result = explorer.decide("migration")
        # With 6 comparisons (3 unique, since each counts for both sides),
        # epistemic value should be moderate -> REFINE or EXPLORE
        assert result.decision in (
            ExplorationDecision.EXPLORE,
            ExplorationDecision.REFINE,
        )


# ---------------------------------------------------------------------------
# ScaffoldExplorer — well-established patterns (SKIP zone)
# ---------------------------------------------------------------------------


class TestExplorerEstablishedPatterns:
    def test_refine_with_many_comparisons_few_patterns(self):
        """With many comparisons but only 2 patterns, epistemic value
        remains moderate (diversity bonus active) — stays REFINE."""
        kg = _build_kg_with_comparisons(40)
        explorer = ScaffoldExplorer(kg, min_comparisons_before_skip=5)

        result = explorer.decide("migration")
        assert result.decision == ExplorationDecision.REFINE

    def test_skip_with_many_comparisons_many_patterns(self):
        """With many comparisons AND diverse patterns (≥4), epistemic
        value drops enough to reach SKIP."""
        kg = InMemoryScaffoldKG()
        strategies = ["quality", "efficiency", "simplicity", "balanced"]
        skills_by_strat = {
            "quality": [("code_analysis", 0), ("synthesis", 1)],
            "efficiency": [("security_review", 0), ("synthesis", 1)],
            "simplicity": [("testing", 0)],
            "balanced": [("code_analysis", 0), ("testing", 1)],
        }
        for i in range(60):
            s = strategies[i % len(strategies)]
            exploit = _make_proposal(s, skills_by_strat[s])
            explore = _make_proposal(
                strategies[(i + 1) % len(strategies)],
                skills_by_strat[strategies[(i + 1) % len(strategies)]],
            )
            comp = _make_comparison("exploit", margin=0.05)
            kg.record_comparison(comp, "migration", exploit, explore)

        explorer = ScaffoldExplorer(kg, min_comparisons_before_skip=5)
        result = explorer.decide("migration")
        assert result.decision == ExplorationDecision.SKIP


# ---------------------------------------------------------------------------
# Session budget exhaustion
# ---------------------------------------------------------------------------


class TestSessionBudget:
    def test_skip_when_budget_exhausted(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg, max_explore_per_session=2)

        # Use up budget
        explorer._session_explores = 2

        result = explorer.decide("migration")
        assert result.decision == ExplorationDecision.SKIP
        assert "budget exhausted" in result.rationale.lower()
        assert result.explore_budget_remaining == 0

    def test_budget_decrements(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg, max_explore_per_session=3)

        r1 = explorer.decide("migration")
        assert r1.decision in (ExplorationDecision.EXPLORE, ExplorationDecision.REFINE)
        assert r1.explore_budget_remaining == 2

        r2 = explorer.decide("migration")
        assert r2.explore_budget_remaining == 1

        r3 = explorer.decide("migration")
        assert r3.explore_budget_remaining == 0

        # Now budget is exhausted
        r4 = explorer.decide("migration")
        assert r4.decision == ExplorationDecision.SKIP


# ---------------------------------------------------------------------------
# reset_session
# ---------------------------------------------------------------------------


class TestResetSession:
    def test_reset_clears_counter(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg, max_explore_per_session=1)

        explorer.decide("migration")  # uses the single slot
        r = explorer.decide("migration")
        assert r.decision == ExplorationDecision.SKIP

        explorer.reset_session()
        r2 = explorer.decide("migration")
        assert r2.decision != ExplorationDecision.SKIP


# ---------------------------------------------------------------------------
# EFE component: _compute_risk
# ---------------------------------------------------------------------------


class TestComputeRisk:
    def test_zero_total_returns_0_2(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        assert explorer._compute_risk(0.5, 0) == pytest.approx(0.2)

    def test_higher_win_rate_higher_risk(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        risk_low = explorer._compute_risk(0.4, 10)
        risk_high = explorer._compute_risk(0.9, 10)
        assert risk_high > risk_low

    def test_risk_is_half_win_rate(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        assert explorer._compute_risk(0.8, 5) == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# EFE component: _compute_ambiguity
# ---------------------------------------------------------------------------


class TestComputeAmbiguity:
    def test_zero_total_returns_1_0(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        assert explorer._compute_ambiguity(0, 0) == pytest.approx(1.0)

    def test_decays_with_log(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        a1 = explorer._compute_ambiguity(1, 1)
        a10 = explorer._compute_ambiguity(10, 3)
        a100 = explorer._compute_ambiguity(100, 5)

        assert a1 > a10 > a100
        # Verify formula: 1 / (1 + log1p(total))
        assert a10 == pytest.approx(1.0 / (1.0 + math.log1p(10)))

    def test_never_negative(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        assert explorer._compute_ambiguity(10000, 50) > 0


# ---------------------------------------------------------------------------
# EFE component: _compute_epistemic
# ---------------------------------------------------------------------------


class TestComputeEpistemic:
    def test_zero_total_returns_1_0(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        assert explorer._compute_epistemic(0, 0) == pytest.approx(1.0)

    def test_diversity_bonus_when_few_patterns(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        # < 4 patterns: gets 0.2 bonus
        with_bonus = explorer._compute_epistemic(5, 2)
        # >= 4 patterns: no bonus
        without_bonus = explorer._compute_epistemic(5, 5)

        assert with_bonus > without_bonus
        assert with_bonus - without_bonus == pytest.approx(0.2)

    def test_decays_with_total(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        e5 = explorer._compute_epistemic(5, 5)
        e20 = explorer._compute_epistemic(20, 5)
        e100 = explorer._compute_epistemic(100, 5)

        assert e5 > e20 > e100

    def test_formula_base_component(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        # No diversity bonus (patterns_seen >= 4)
        result = explorer._compute_epistemic(10, 4)
        expected = 1.0 / (1.0 + 10 * 0.5)
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Natural lifecycle: EXPLORE -> REFINE -> SKIP transition
# ---------------------------------------------------------------------------


class TestLifecycleTransition:
    def test_progressive_transition(self):
        """Feed comparisons progressively with diverse patterns and verify
        the explorer transitions from EXPLORE → REFINE → SKIP."""
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(
            kg,
            min_comparisons_before_skip=5,
            max_explore_per_session=100,
        )

        strategies = ["quality", "efficiency", "simplicity", "balanced"]
        skills_sets = {
            "quality": [("code_analysis", 0), ("synthesis", 1)],
            "efficiency": [("security_review", 0), ("synthesis", 1)],
            "simplicity": [("testing", 0)],
            "balanced": [("code_analysis", 0), ("testing", 1)],
        }
        decisions = []

        for i in range(60):
            result = explorer.decide("migration")
            decisions.append(result.decision)

            s1 = strategies[i % len(strategies)]
            s2 = strategies[(i + 1) % len(strategies)]
            exploit = _make_proposal(s1, skills_sets[s1])
            explore = _make_proposal(s2, skills_sets[s2])
            comp = _make_comparison("exploit", margin=0.05)
            kg.record_comparison(comp, "migration", exploit, explore)

        early = decisions[:3]
        assert all(d == ExplorationDecision.EXPLORE for d in early), (
            f"Early decisions should all be EXPLORE, got {early}"
        )

        late = decisions[-5:]
        assert ExplorationDecision.SKIP in late, (
            f"Late decisions should include SKIP, got {late}"
        )

    def test_explores_then_refines_with_few_patterns(self):
        """With only 2 patterns, transitions from EXPLORE to REFINE
        (never reaches SKIP due to diversity bonus)."""
        kg_empty = InMemoryScaffoldKG()
        explorer_empty = ScaffoldExplorer(kg_empty, min_comparisons_before_skip=3)
        assert explorer_empty.decide("test").decision == ExplorationDecision.EXPLORE

        kg_moderate = _build_kg_with_comparisons(20)
        explorer_moderate = ScaffoldExplorer(kg_moderate, min_comparisons_before_skip=3)
        assert explorer_moderate.decide("migration").decision == ExplorationDecision.REFINE


# ---------------------------------------------------------------------------
# ExplorationResult fields
# ---------------------------------------------------------------------------


class TestExplorationResult:
    def test_result_fields(self):
        kg = InMemoryScaffoldKG()
        explorer = ScaffoldExplorer(kg)

        result = explorer.decide("test_type")
        assert isinstance(result.decision, ExplorationDecision)
        assert isinstance(result.efe_score, EFEScore)
        assert isinstance(result.rationale, str)
        assert isinstance(result.explore_budget_remaining, int)
        assert result.explore_budget_remaining >= 0


# ---------------------------------------------------------------------------
# Custom EFE weights
# ---------------------------------------------------------------------------


class TestCustomWeights:
    def test_custom_weights_applied(self):
        kg = InMemoryScaffoldKG()
        weights = EFEWeights(risk=0.1, ambiguity=0.1, epistemic=0.8)
        explorer = ScaffoldExplorer(kg, efe_weights=weights)

        result = explorer.decide("migration")
        # With high epistemic weight, empty KG should strongly favor exploration
        assert result.decision == ExplorationDecision.EXPLORE
