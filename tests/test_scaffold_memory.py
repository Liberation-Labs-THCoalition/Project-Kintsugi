"""Tests for kintsugi.kintsugi_engine.scaffold_memory."""

from __future__ import annotations

import pytest

from kintsugi.kintsugi_engine.scaffold_memory import (
    InMemoryScaffoldKG,
    ScaffoldRecord,
)
from kintsugi.kintsugi_engine.scaffold_comparator import ScaffoldComparison
from kintsugi.kintsugi_engine.scaffold_generator import ScaffoldProposal
from kintsugi.skills.dag import DAGNode, SkillDAG


# ---------------------------------------------------------------------------
# Helpers — lightweight mock proposals and comparisons
# ---------------------------------------------------------------------------


def _make_dag(strategy: str, nodes: list[tuple[str, int]]) -> SkillDAG:
    """Build a minimal SkillDAG with named nodes at specified layers."""
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
    """Helper to record a single comparison into the KG."""
    exploit = _make_proposal(exploit_strategy, EXPLOIT_SKILLS)
    explore = _make_proposal(explore_strategy, EXPLORE_SKILLS)
    comp = _make_comparison(winner, margin=margin)
    kg.record_comparison(comp, task_type, exploit, explore)


# ---------------------------------------------------------------------------
# ScaffoldRecord dataclass defaults
# ---------------------------------------------------------------------------


class TestScaffoldRecord:
    def test_defaults(self):
        rec = ScaffoldRecord(
            task_type="review",
            winner_pattern="quality",
            loser_pattern="efficiency",
            margin=0.15,
            winner_skills=["a"],
            loser_skills=["b"],
        )
        assert rec.timestamp == ""
        assert rec.task_type == "review"
        assert rec.margin == 0.15

    def test_explicit_timestamp(self):
        rec = ScaffoldRecord(
            task_type="review",
            winner_pattern="quality",
            loser_pattern="efficiency",
            margin=0.1,
            winner_skills=[],
            loser_skills=[],
            timestamp="2026-06-01T00:00:00",
        )
        assert rec.timestamp == "2026-06-01T00:00:00"


# ---------------------------------------------------------------------------
# InMemoryScaffoldKG — record_comparison
# ---------------------------------------------------------------------------


class TestRecordComparison:
    def test_exploit_wins_updates_counts(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")

        assert kg._wins[("quality", "migration")] == 1
        assert kg._losses[("efficiency", "migration")] == 1
        assert kg._head_to_head[("quality", "efficiency")] == 1
        assert kg.total_comparisons == 1

    def test_explore_wins_updates_counts(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "explore")

        assert kg._wins[("efficiency", "migration")] == 1
        assert kg._losses[("quality", "migration")] == 1
        assert kg._head_to_head[("efficiency", "quality")] == 1

    def test_tie_records_no_win_loss(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "tie")

        # Tie should not increment wins/losses
        assert kg._wins.get(("quality", "migration"), 0) == 0
        assert kg._wins.get(("efficiency", "migration"), 0) == 0
        assert kg._losses.get(("quality", "migration"), 0) == 0
        assert kg._losses.get(("efficiency", "migration"), 0) == 0
        # Head-to-head should not be updated for tie
        assert len(kg._head_to_head) == 0
        # But record still stored
        assert kg.total_comparisons == 1
        assert kg._records[0].winner_pattern == "tie"
        assert kg._records[0].loser_pattern == "tie"

    def test_multiple_comparisons_accumulate(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")
        _record_one(kg, "exploit")
        _record_one(kg, "explore")

        assert kg._wins[("quality", "migration")] == 2
        assert kg._losses[("quality", "migration")] == 1
        assert kg._wins[("efficiency", "migration")] == 1
        assert kg._losses[("efficiency", "migration")] == 2
        assert kg.total_comparisons == 3

    def test_skill_combos_tracked(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")

        assert "quality" in kg._skill_combos
        assert "efficiency" in kg._skill_combos
        assert len(kg._skill_combos["quality"]) >= 1
        assert len(kg._skill_combos["efficiency"]) >= 1


# ---------------------------------------------------------------------------
# get_preferred_patterns
# ---------------------------------------------------------------------------


class TestGetPreferredPatterns:
    def test_sorted_by_win_rate(self):
        kg = InMemoryScaffoldKG()
        # quality wins 3, loses 1  -> 75%
        for _ in range(3):
            _record_one(kg, "exploit")
        _record_one(kg, "explore")  # efficiency wins 1, loses 3 -> 25%

        preferred = kg.get_preferred_patterns("migration")
        assert preferred[0] == "quality"
        assert "efficiency" in preferred

    def test_empty_for_unknown_task_type(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit", task_type="migration")

        assert kg.get_preferred_patterns("unknown_task") == []

    def test_top_n_limits_results(self):
        kg = InMemoryScaffoldKG()
        # Create patterns with different strategies
        for strat in ["s1", "s2", "s3", "s4", "s5"]:
            exploit = _make_proposal(strat, [("code_analysis", 0)])
            explore = _make_proposal("baseline", [("synthesis", 0)])
            comp = _make_comparison("exploit")
            kg.record_comparison(comp, "review", exploit, explore)

        result = kg.get_preferred_patterns("review", top_n=2)
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# get_avoided_patterns
# ---------------------------------------------------------------------------


class TestGetAvoidedPatterns:
    def test_returns_high_loss_rate_patterns(self):
        kg = InMemoryScaffoldKG()
        # efficiency loses 3 out of 4 -> 75% loss rate, total >=2
        for _ in range(3):
            _record_one(kg, "exploit")
        _record_one(kg, "explore")

        avoided = kg.get_avoided_patterns("migration")
        assert "efficiency" in avoided

    def test_excludes_low_loss_rate(self):
        kg = InMemoryScaffoldKG()
        # efficiency wins 2, loses 1 -> 33% loss rate
        _record_one(kg, "explore")
        _record_one(kg, "explore")
        _record_one(kg, "exploit")

        avoided = kg.get_avoided_patterns("migration")
        assert "quality" not in avoided or len(avoided) == 0

    def test_excludes_insufficient_data(self):
        kg = InMemoryScaffoldKG()
        # Only 1 comparison total — doesn't meet >= 2 threshold
        _record_one(kg, "exploit")

        avoided = kg.get_avoided_patterns("migration")
        assert "efficiency" not in avoided


# ---------------------------------------------------------------------------
# get_win_rates
# ---------------------------------------------------------------------------


class TestGetWinRates:
    def test_correct_rates(self):
        kg = InMemoryScaffoldKG()
        for _ in range(3):
            _record_one(kg, "exploit")
        _record_one(kg, "explore")

        rates = kg.get_win_rates("migration")
        assert rates["quality"] == pytest.approx(0.75)
        # efficiency: 1 win out of 4 = 0.25
        assert rates["efficiency"] == pytest.approx(0.25)

    def test_empty_for_unknown_task(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit", task_type="migration")

        assert kg.get_win_rates("unknown") == {}


# ---------------------------------------------------------------------------
# to_scaffold_memory
# ---------------------------------------------------------------------------


class TestToScaffoldMemory:
    def test_returns_valid_scaffold_memory(self):
        kg = InMemoryScaffoldKG()
        for _ in range(4):
            _record_one(kg, "exploit")

        mem = kg.to_scaffold_memory("migration")
        assert isinstance(mem.preferred_patterns, list)
        assert isinstance(mem.avoided_patterns, list)
        assert isinstance(mem.win_rates, dict)
        assert "quality" in mem.preferred_patterns


# ---------------------------------------------------------------------------
# should_promote
# ---------------------------------------------------------------------------


class TestShouldPromote:
    def test_requires_both_min_wins_and_min_rate(self):
        kg = InMemoryScaffoldKG()
        # quality: 3 wins, 1 loss = 75%  -> meets default min_wins=3, min_rate=0.65
        for _ in range(3):
            _record_one(kg, "exploit")
        _record_one(kg, "explore")

        assert kg.should_promote("quality", "migration") is True

    def test_false_with_insufficient_data(self):
        kg = InMemoryScaffoldKG()
        # quality: 2 wins, 0 losses = 100% rate but only 2 total (< min_wins=3)
        _record_one(kg, "exploit")
        _record_one(kg, "exploit")

        assert kg.should_promote("quality", "migration") is False

    def test_false_with_low_rate(self):
        kg = InMemoryScaffoldKG()
        # quality: 3 wins, 3 losses = 50% rate (< min_rate=0.65)
        for _ in range(3):
            _record_one(kg, "exploit")
        for _ in range(3):
            _record_one(kg, "explore")

        assert kg.should_promote("quality", "migration") is False

    def test_custom_thresholds(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")
        _record_one(kg, "exploit")

        # With min_wins=2 and min_rate=0.5, should pass
        assert kg.should_promote("quality", "migration",
                                 min_wins=2, min_rate=0.5) is True

    def test_unknown_pattern(self):
        kg = InMemoryScaffoldKG()
        assert kg.should_promote("nonexistent", "migration") is False


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_correct_counts(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit", task_type="migration")
        _record_one(kg, "explore", task_type="review")

        s = kg.stats()
        assert s["total_comparisons"] == 2
        assert s["patterns_seen"] == 2  # quality + efficiency
        assert s["task_types_seen"] == 2  # migration + review
        assert s["head_to_head_pairs"] == 2

    def test_empty_kg(self):
        kg = InMemoryScaffoldKG()
        s = kg.stats()
        assert s["total_comparisons"] == 0
        assert s["patterns_seen"] == 0
        assert s["task_types_seen"] == 0
        assert s["head_to_head_pairs"] == 0


# ---------------------------------------------------------------------------
# serialize / deserialize round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_serialize_produces_json_safe_dict(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")

        data = kg.serialize()
        assert isinstance(data, dict)
        assert isinstance(data["wins"], dict)
        assert isinstance(data["losses"], dict)
        assert isinstance(data["head_to_head"], dict)
        assert isinstance(data["skill_combos"], dict)
        assert isinstance(data["records"], list)

        # Keys must be strings (JSON-safe)
        for key in data["wins"]:
            assert isinstance(key, str)
        # Skill combos values must be lists (not sets)
        for val in data["skill_combos"].values():
            assert isinstance(val, list)

    def test_deserialize_round_trip(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit", task_type="migration")
        _record_one(kg, "explore", task_type="migration")
        _record_one(kg, "tie", task_type="review")

        data = kg.serialize()
        kg2 = InMemoryScaffoldKG.deserialize(data)

        assert kg2.total_comparisons == 3
        assert kg2._wins == dict(kg._wins)
        assert kg2._losses == dict(kg._losses)
        assert kg2._head_to_head == dict(kg._head_to_head)

    def test_deserialize_preserves_records(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit", margin=0.42)

        data = kg.serialize()
        kg2 = InMemoryScaffoldKG.deserialize(data)

        assert len(kg2._records) == 1
        assert kg2._records[0].task_type == "migration"
        assert kg2._records[0].margin == pytest.approx(0.42)

    def test_deserialize_preserves_skill_combos(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")

        data = kg.serialize()
        kg2 = InMemoryScaffoldKG.deserialize(data)

        assert kg2._skill_combos.keys() == kg._skill_combos.keys()
        for key in kg._skill_combos:
            assert kg2._skill_combos[key] == kg._skill_combos[key]

    def test_deserialize_empty(self):
        kg = InMemoryScaffoldKG.deserialize({})
        assert kg.total_comparisons == 0
        assert kg.stats()["patterns_seen"] == 0


# ---------------------------------------------------------------------------
# total_comparisons property
# ---------------------------------------------------------------------------


class TestTotalComparisons:
    def test_starts_at_zero(self):
        kg = InMemoryScaffoldKG()
        assert kg.total_comparisons == 0

    def test_increments_with_records(self):
        kg = InMemoryScaffoldKG()
        _record_one(kg, "exploit")
        assert kg.total_comparisons == 1
        _record_one(kg, "explore")
        assert kg.total_comparisons == 2
        _record_one(kg, "tie")
        assert kg.total_comparisons == 3
