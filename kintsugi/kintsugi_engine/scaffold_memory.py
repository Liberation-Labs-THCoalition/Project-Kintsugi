"""Scaffold Memory — KG-backed learning from scaffold comparisons.

Phase 3 of Adaptive Scaffold Evolution. Records scaffold comparison
outcomes into a knowledge graph and retrieves preferred patterns for
future scaffold generation.

Entity types:
  SCAFFOLD_PATTERN: e.g., "parallel_then_gate", "sequential_deep"
  TASK_TYPE: e.g., "migration_question", "code_review", "security_audit"
  SKILL_COMBO: e.g., "code_analysis+security_review+synthesis"

Key predicates:
  (SCAFFOLD_PATTERN, won_for, TASK_TYPE) — weight = win count
  (SCAFFOLD_PATTERN, lost_for, TASK_TYPE) — weight = loss count
  (SKILL_COMBO, used_in, SCAFFOLD_PATTERN)
  (SCAFFOLD_PATTERN, beat, SCAFFOLD_PATTERN) — head-to-head
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from kintsugi.kintsugi_engine.scaffold_comparator import ScaffoldComparison
from kintsugi.kintsugi_engine.scaffold_generator import ScaffoldMemory, ScaffoldProposal

logger = logging.getLogger(__name__)


@dataclass
class ScaffoldRecord:
    """A recorded scaffold comparison for persistence."""
    task_type: str
    winner_pattern: str
    loser_pattern: str
    margin: float
    winner_skills: list[str]
    loser_skills: list[str]
    timestamp: str = ""


class InMemoryScaffoldKG:
    """In-memory knowledge graph for scaffold pattern learning.

    Uses the same PPR pattern as sovereign_kg.py but without PostgreSQL
    dependency — stores edges in memory for fast iteration during
    development. Phase 5 migrates to PostgreSQL if needed.
    """

    def __init__(self):
        self._wins: dict[tuple[str, str], int] = defaultdict(int)
        self._losses: dict[tuple[str, str], int] = defaultdict(int)
        self._head_to_head: dict[tuple[str, str], int] = defaultdict(int)
        self._skill_combos: dict[str, set[str]] = defaultdict(set)
        self._records: list[ScaffoldRecord] = []

    @property
    def total_comparisons(self) -> int:
        return len(self._records)

    def record_comparison(self, comparison: ScaffoldComparison,
                          task_type: str,
                          exploit_proposal: ScaffoldProposal,
                          explore_proposal: ScaffoldProposal) -> None:
        """Record a scaffold comparison outcome."""
        exploit_pattern = exploit_proposal.strategy
        explore_pattern = explore_proposal.strategy
        exploit_skills = sorted(exploit_proposal.dag.nodes.keys())
        explore_skills = sorted(explore_proposal.dag.nodes.keys())

        exploit_combo = "+".join(n.skill_name for n in
                                sorted(exploit_proposal.dag.nodes.values(),
                                       key=lambda n: n.layer))
        explore_combo = "+".join(n.skill_name for n in
                                sorted(explore_proposal.dag.nodes.values(),
                                       key=lambda n: n.layer))

        if comparison.winner == "exploit":
            self._wins[(exploit_pattern, task_type)] += 1
            self._losses[(explore_pattern, task_type)] += 1
            self._head_to_head[(exploit_pattern, explore_pattern)] += 1
            winner_pattern = exploit_pattern
            loser_pattern = explore_pattern
        elif comparison.winner == "explore":
            self._wins[(explore_pattern, task_type)] += 1
            self._losses[(exploit_pattern, task_type)] += 1
            self._head_to_head[(explore_pattern, exploit_pattern)] += 1
            winner_pattern = explore_pattern
            loser_pattern = exploit_pattern
        else:
            winner_pattern = "tie"
            loser_pattern = "tie"

        self._skill_combos[exploit_pattern].add(exploit_combo)
        self._skill_combos[explore_pattern].add(explore_combo)

        self._records.append(ScaffoldRecord(
            task_type=task_type,
            winner_pattern=winner_pattern,
            loser_pattern=loser_pattern,
            margin=comparison.margin,
            winner_skills=exploit_skills if comparison.winner == "exploit" else explore_skills,
            loser_skills=explore_skills if comparison.winner == "exploit" else exploit_skills,
            timestamp=comparison.timestamp,
        ))

        logger.info(
            "Scaffold KG: %s beat %s for %s (margin %.3f, total %d comparisons)",
            winner_pattern, loser_pattern, task_type,
            comparison.margin, self.total_comparisons,
        )

    def get_preferred_patterns(self, task_type: str, top_n: int = 3) -> list[str]:
        """Return the top-N scaffold patterns for a task type by win rate."""
        patterns = set()
        for (pattern, tt), wins in self._wins.items():
            if tt == task_type:
                patterns.add(pattern)
        for (pattern, tt), losses in self._losses.items():
            if tt == task_type:
                patterns.add(pattern)

        if not patterns:
            return []

        ranked = []
        for pattern in patterns:
            wins = self._wins.get((pattern, task_type), 0)
            losses = self._losses.get((pattern, task_type), 0)
            total = wins + losses
            win_rate = wins / total if total > 0 else 0.5
            ranked.append((pattern, win_rate, total))

        ranked.sort(key=lambda x: (-x[1], -x[2]))
        return [p for p, _, _ in ranked[:top_n]]

    def get_avoided_patterns(self, task_type: str, top_n: int = 3) -> list[str]:
        """Return patterns that consistently lose for a task type."""
        patterns = set()
        for (pattern, tt), losses in self._losses.items():
            if tt == task_type:
                patterns.add(pattern)

        avoided = []
        for pattern in patterns:
            wins = self._wins.get((pattern, task_type), 0)
            losses = self._losses.get((pattern, task_type), 0)
            total = wins + losses
            if total >= 2 and losses / total > 0.7:
                avoided.append(pattern)

        return avoided[:top_n]

    def get_win_rates(self, task_type: str) -> dict[str, float]:
        """Return win rates for all patterns seen on a task type."""
        rates = {}
        for (pattern, tt), wins in self._wins.items():
            if tt == task_type:
                losses = self._losses.get((pattern, tt), 0)
                total = wins + losses
                rates[pattern] = wins / total if total > 0 else 0.5
        return rates

    def to_scaffold_memory(self, task_type: str) -> ScaffoldMemory:
        """Convert KG state to a ScaffoldMemory for the generator."""
        return ScaffoldMemory(
            preferred_patterns=self.get_preferred_patterns(task_type),
            avoided_patterns=self.get_avoided_patterns(task_type),
            win_rates=self.get_win_rates(task_type),
        )

    def should_promote(self, pattern: str, task_type: str,
                       min_wins: int = 3, min_rate: float = 0.65) -> bool:
        """Should a pattern be promoted to default exploit for this task type?

        Requires at least min_wins AND min_rate to prevent premature promotion
        from a single lucky comparison.
        """
        wins = self._wins.get((pattern, task_type), 0)
        losses = self._losses.get((pattern, task_type), 0)
        total = wins + losses
        if total < min_wins:
            return False
        return (wins / total) >= min_rate

    def stats(self) -> dict[str, Any]:
        """Return summary statistics."""
        patterns_seen = set()
        for (p, _) in self._wins:
            patterns_seen.add(p)
        for (p, _) in self._losses:
            patterns_seen.add(p)

        task_types = set()
        for (_, tt) in self._wins:
            task_types.add(tt)
        for (_, tt) in self._losses:
            task_types.add(tt)

        return {
            "total_comparisons": self.total_comparisons,
            "patterns_seen": len(patterns_seen),
            "task_types_seen": len(task_types),
            "head_to_head_pairs": len(self._head_to_head),
        }

    def serialize(self) -> dict:
        """Serialize for persistence (JSON-safe)."""
        return {
            "wins": {f"{p}|{tt}": v for (p, tt), v in self._wins.items()},
            "losses": {f"{p}|{tt}": v for (p, tt), v in self._losses.items()},
            "head_to_head": {f"{p}|{l}": v for (p, l), v in self._head_to_head.items()},
            "records": [
                {"task_type": r.task_type, "winner": r.winner_pattern,
                 "loser": r.loser_pattern, "margin": r.margin,
                 "timestamp": r.timestamp}
                for r in self._records
            ],
        }

    @classmethod
    def deserialize(cls, data: dict) -> "InMemoryScaffoldKG":
        """Reconstruct from serialized data."""
        kg = cls()
        for key, val in data.get("wins", {}).items():
            p, tt = key.split("|", 1)
            kg._wins[(p, tt)] = val
        for key, val in data.get("losses", {}).items():
            p, tt = key.split("|", 1)
            kg._losses[(p, tt)] = val
        for key, val in data.get("head_to_head", {}).items():
            p, l = key.split("|", 1)
            kg._head_to_head[(p, l)] = val
        return kg
