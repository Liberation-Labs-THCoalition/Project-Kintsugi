"""Temporal Scorer — four-factor retrieval scoring with Ebbinghaus decay.

Vendored and adapted from Project Mnemosyne's h-mem-temporal component.
Extends two-factor scoring (semantic + entity count) with temporal
relevance and robustness decay, using the TemporalTree as the source of
reinforcement/contradiction history.

Score = alpha*Semantic + beta*EntityCount + gamma*Temporal + delta*Robustness
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from kintsugi.memory.temporal_tree import (
    TemporalTree, TreeNode, TimeScope,
    ebbinghaus_decay, temporal_iou,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Configurable weights for four-factor scoring."""
    semantic: float = 0.35
    entity_count: float = 0.15
    temporal: float = 0.20
    robustness: float = 0.30

    def validate(self):
        total = self.semantic + self.entity_count + self.temporal + self.robustness
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


@dataclass
class ScoredResult:
    """A retrieval result with all four scoring factors."""
    content: str
    node_id: int | None = None
    semantic_score: float = 0.0
    entity_score: float = 0.0
    temporal_score: float = 0.0
    robustness_score: float = 0.0
    combined_score: float = 0.0
    source: str = ''
    level: int = 0
    contradicted: bool = False
    metadata: dict = field(default_factory=dict)


class TemporalScorer:
    """Scores retrieval results with temporal awareness and decay.

    Takes results from hybrid retrieval (which already has semantic +
    entity scores) and adds temporal relevance and Ebbinghaus robustness
    scoring, backed by a TemporalTree.
    """

    def __init__(self, tree: TemporalTree, weights: ScoringWeights | None = None,
                 tau: float = 604800, eta: float = 0.5):
        self.tree = tree
        self.weights = weights or ScoringWeights()
        self.weights.validate()
        self.tau = tau
        self.eta = eta

    def score_results(self, tgs_results: list[dict],
                      query_time_hint: tuple[float, float] | None = None,
                      now: float | None = None) -> list[ScoredResult]:
        """Score retrieval results with temporal + robustness factors.

        Args:
            tgs_results: Results from hybrid retrieval, each with
                         'content', 'tgs_score', 'source', optionally 'id'.
            query_time_hint: (start, end) for temporal relevance scoring.
                             None uses (now - 1 week, now).
            now: Current time override (for testing).
        """
        t = now or time.time()
        w = self.weights

        if query_time_hint is None:
            query_time_hint = (t - 604800, t)

        scored = []
        for result in tgs_results:
            content = result.get('content', '')
            tgs_score = result.get('tgs_score', 0.5)

            node = self._find_matching_node(content, result.get('id'))

            if node:
                temporal = temporal_iou(
                    query_time_hint[0], query_time_hint[1],
                    node.window_start, node.window_end
                )
                robustness = ebbinghaus_decay(
                    t, node.last_reinforced or node.timestamp,
                    node.reinforcement_count, self.tau, self.eta
                )
                contradicted = node.contradicted_by is not None
                level = node.level
                node_id = node.id

                if contradicted:
                    robustness *= 0.1
            else:
                temporal = 0.5
                robustness = 0.5
                contradicted = False
                level = 0
                node_id = None

            entity_score = result.get('rec_count', 0)
            max_entity = max(r.get('rec_count', 0) for r in tgs_results) or 1
            norm_entity = entity_score / max_entity

            combined = (
                w.semantic * tgs_score +
                w.entity_count * norm_entity +
                w.temporal * temporal +
                w.robustness * robustness
            )

            scored.append(ScoredResult(
                content=content,
                node_id=node_id,
                semantic_score=tgs_score,
                entity_score=norm_entity,
                temporal_score=temporal,
                robustness_score=robustness,
                combined_score=combined,
                source=result.get('source', ''),
                level=level,
                contradicted=contradicted,
                metadata=result.get('metadata', {}),
            ))

        scored.sort(key=lambda r: r.combined_score, reverse=True)
        return scored

    def _find_matching_node(self, content: str,
                             memory_id: int | None = None) -> TreeNode | None:
        """Find the tree node matching this retrieval result."""
        if memory_id:
            row = self.tree.conn.execute(
                "SELECT id FROM tree_nodes WHERE id = ?", (memory_id,)
            ).fetchone()
            if row:
                return self.tree.get_node(row[0])

        preview = content[:200]
        row = self.tree.conn.execute(
            "SELECT id FROM tree_nodes WHERE content LIKE ? LIMIT 1",
            (f"{preview}%",)
        ).fetchone()
        if row:
            return self.tree.get_node(row[0])

        return None


class QueryScoper:
    """Decomposes queries into SHORT/LONG/MIXED with temporal hints.

    Detects temporal language in queries to determine:
    - Time scope: "last week" -> SHORT, "what's the consensus" -> LONG
    - Time range: "in April" -> (april_start, april_end)
    """

    RECENT_MARKERS = [
        'today', 'yesterday', 'this morning', 'last night',
        'this week', 'recent', 'latest', 'just', 'now',
    ]

    HISTORICAL_MARKERS = [
        'consensus', 'established', 'validated', 'overall',
        'history', 'always', 'generally', 'long-term',
    ]

    def scope_query(self, query: str) -> tuple[TimeScope, tuple[float, float] | None]:
        """Determine scope and time hint from query text."""
        q_lower = query.lower()

        has_recent = any(m in q_lower for m in self.RECENT_MARKERS)
        has_historical = any(m in q_lower for m in self.HISTORICAL_MARKERS)

        if has_recent and not has_historical:
            scope = TimeScope.SHORT
            now = time.time()
            if 'today' in q_lower or 'this morning' in q_lower:
                hint = (now - 86400, now)
            elif 'yesterday' in q_lower or 'last night' in q_lower:
                hint = (now - 172800, now - 86400)
            elif 'this week' in q_lower:
                hint = (now - 604800, now)
            else:
                hint = (now - 604800, now)
        elif has_historical and not has_recent:
            scope = TimeScope.LONG
            hint = None
        else:
            scope = TimeScope.MIXED
            hint = None

        return scope, hint
