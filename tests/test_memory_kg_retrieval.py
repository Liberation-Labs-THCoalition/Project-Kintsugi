"""Tests for kintsugi.memory.kg_retrieval — PPR + CatRAG math (pure numpy,
no database dependency)."""

from __future__ import annotations

import numpy as np
import pytest

from kintsugi.memory.kg_retrieval import (
    PPRConfig,
    apply_catrag_weighting,
    personalized_pagerank,
)


class TestPersonalizedPageRank:
    def test_empty_graph_returns_empty_array(self):
        adjacency = np.zeros((0, 0))
        scores = personalized_pagerank(adjacency, {})
        assert scores.size == 0

    def test_scores_sum_close_to_one(self):
        # Triangle graph: 0-1, 1-2, 0-2
        adjacency = np.array([
            [0, 1, 1],
            [1, 0, 1],
            [1, 1, 0],
        ], dtype=np.float64)
        scores = personalized_pagerank(adjacency, {0: 1.0})
        assert scores.sum() == pytest.approx(1.0, abs=1e-3)

    def test_seed_node_scores_highest_in_star_graph(self):
        # Star graph: node 0 is the hub connected to 1, 2, 3 (no other edges)
        n = 4
        adjacency = np.zeros((n, n))
        for i in range(1, n):
            adjacency[0, i] = 1.0
            adjacency[i, 0] = 1.0

        scores = personalized_pagerank(adjacency, {1: 1.0}, PPRConfig(alpha=0.15))
        # The seed itself (node 1) should score at least as high as the
        # other leaf nodes it wasn't seeded from.
        assert scores[1] >= scores[2]
        assert scores[1] >= scores[3]

    def test_uniform_personalization_when_no_seeds(self):
        adjacency = np.array([[0, 1], [1, 0]], dtype=np.float64)
        scores = personalized_pagerank(adjacency, {})
        assert scores[0] == pytest.approx(scores[1], abs=1e-6)

    def test_dangling_node_does_not_crash(self):
        # Node 1 has no outgoing edges at all
        adjacency = np.array([
            [0, 0],
            [0, 0],
        ], dtype=np.float64)
        scores = personalized_pagerank(adjacency, {0: 1.0})
        assert scores.shape == (2,)
        assert not np.isnan(scores).any()

    def test_converges_within_max_iterations(self):
        adjacency = np.array([
            [0, 1, 0],
            [1, 0, 1],
            [0, 1, 0],
        ], dtype=np.float64)
        config = PPRConfig(max_iterations=5, tolerance=1e-12)
        scores = personalized_pagerank(adjacency, {0: 1.0}, config)
        assert scores.shape == (3,)


class TestCatRAGWeighting:
    def test_matching_predicate_embedding_preserves_weight(self):
        adjacency = np.array([[0, 1], [1, 0]], dtype=np.float64)
        query_emb = np.array([1.0, 0.0])
        edge_meta = [{
            "subject_idx": 0, "object_idx": 1,
            "predicate_embedding": [1.0, 0.0],  # identical to query
        }]

        weighted = apply_catrag_weighting(adjacency, edge_meta, query_emb, temperature=0.1)
        assert weighted[0, 1] == pytest.approx(adjacency[0, 1], rel=0.05)

    def test_orthogonal_predicate_embedding_suppresses_weight(self):
        adjacency = np.array([[0, 1], [1, 0]], dtype=np.float64)
        query_emb = np.array([1.0, 0.0])
        edge_meta = [{
            "subject_idx": 0, "object_idx": 1,
            "predicate_embedding": [0.0, 1.0],  # orthogonal to query
        }]

        weighted = apply_catrag_weighting(adjacency, edge_meta, query_emb, temperature=0.1)
        assert weighted[0, 1] < adjacency[0, 1]

    def test_missing_predicate_embedding_leaves_weight_unchanged(self):
        adjacency = np.array([[0, 1], [1, 0]], dtype=np.float64)
        query_emb = np.array([1.0, 0.0])
        edge_meta = [{"subject_idx": 0, "object_idx": 1, "predicate_embedding": None}]

        weighted = apply_catrag_weighting(adjacency, edge_meta, query_emb)
        assert weighted[0, 1] == adjacency[0, 1]

    def test_weighting_is_symmetric(self):
        adjacency = np.array([[0, 1], [1, 0]], dtype=np.float64)
        query_emb = np.array([1.0, 0.0])
        edge_meta = [{
            "subject_idx": 0, "object_idx": 1,
            "predicate_embedding": [0.5, 0.5],
        }]

        weighted = apply_catrag_weighting(adjacency, edge_meta, query_emb)
        assert weighted[0, 1] == weighted[1, 0]
