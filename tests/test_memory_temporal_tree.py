"""Tests for kintsugi.memory.temporal_tree."""

from __future__ import annotations

import math
import time

import pytest

from kintsugi.memory.temporal_tree import (
    LEVEL_SIMILARITY_THRESHOLDS,
    LEVEL_WINDOWS,
    TemporalTree,
    TimeScope,
    ebbinghaus_decay,
    temporal_iou,
)


@pytest.fixture
def tree():
    t = TemporalTree(":memory:")
    yield t
    t.close()


class TestEbbinghausDecay:
    def test_no_elapsed_time_returns_full_robustness(self):
        now = time.time()
        assert ebbinghaus_decay(now, now, 0) == 1.0

    def test_decays_over_time(self):
        now = time.time()
        recent = ebbinghaus_decay(now, now - 3600, 0)
        old = ebbinghaus_decay(now, now - 3600 * 24 * 30, 0)
        assert recent > old

    def test_reinforcement_slows_decay(self):
        now = time.time()
        elapsed = now - 604800  # 1 week ago
        unreinforced = ebbinghaus_decay(now, elapsed, 0)
        reinforced = ebbinghaus_decay(now, elapsed, 10)
        assert reinforced > unreinforced

    def test_bounded_between_zero_and_one(self):
        now = time.time()
        val = ebbinghaus_decay(now, now - 1e9, 0)
        assert 0.0 <= val <= 1.0


class TestTemporalIoU:
    def test_identical_intervals_score_one(self):
        score = temporal_iou(0, 100, 0, 100)
        assert math.isclose(score, 1.0)

    def test_disjoint_intervals_score_low(self):
        score = temporal_iou(0, 10, 1000, 1010)
        assert score < 0.1

    def test_partial_overlap_between_zero_and_one(self):
        score = temporal_iou(0, 100, 50, 150)
        assert 0.0 < score < 1.0


class TestTemporalTreeBasics:
    def test_add_leaf_returns_id(self, tree):
        node_id = tree.add_leaf("hello world")
        assert isinstance(node_id, int)

    def test_get_node_roundtrip(self, tree):
        node_id = tree.add_leaf("content here", metadata={"k": "v"})
        node = tree.get_node(node_id)
        assert node is not None
        assert node.content == "content here"
        assert node.level == 0
        assert node.metadata == {"k": "v"}

    def test_get_node_missing_returns_none(self, tree):
        assert tree.get_node(99999) is None

    def test_get_unconsolidated_leaves(self, tree):
        tree.add_leaf("a")
        tree.add_leaf("b")
        leaves = tree.get_unconsolidated_leaves(0)
        assert len(leaves) == 2

    def test_create_parent_consolidates_children(self, tree):
        id1 = tree.add_leaf("a", timestamp=1000)
        id2 = tree.add_leaf("b", timestamp=2000)
        c1, c2 = tree.get_node(id1), tree.get_node(id2)

        parent_id = tree.create_parent([c1, c2], "summary of a and b", level=1)
        parent = tree.get_node(parent_id)

        assert parent.level == 1
        assert parent.content == "summary of a and b"
        assert set(parent.children_ids) == {id1, id2}

        # Children now have a parent and are no longer "unconsolidated"
        assert tree.get_node(id1).parent_id == parent_id
        assert tree.get_unconsolidated_leaves(0) == []

    def test_reinforce_increments_count(self, tree):
        node_id = tree.add_leaf("finding")
        tree.reinforce(node_id)
        tree.reinforce(node_id, amount=2)
        node = tree.get_node(node_id)
        assert node.reinforcement_count == 3

    def test_contradict_resets_reinforcement_and_links(self, tree):
        node_id = tree.add_leaf("finding")
        tree.reinforce(node_id, amount=5)
        contradictor_id = tree.add_leaf("opposing finding")

        tree.contradict(node_id, contradictor_id)
        node = tree.get_node(node_id)
        assert node.reinforcement_count == 0
        assert node.contradicted_by == contradictor_id

    def test_search_scopes_by_level(self, tree):
        leaf_id = tree.add_leaf("leaf", timestamp=1000)
        leaf = tree.get_node(leaf_id)
        parent_id = tree.create_parent([leaf], "summary", level=2)

        short_results = tree.search(TimeScope.SHORT)
        long_results = tree.search(TimeScope.LONG)

        assert any(n.id == leaf_id for n in short_results)
        assert all(n.id != parent_id for n in short_results)
        assert any(n.id == parent_id for n in long_results)

    def test_stats_counts_per_level(self, tree):
        tree.add_leaf("a")
        tree.add_leaf("b")
        stats = tree.stats()
        assert stats["total_nodes"] == 2
        assert stats["per_level"][0] == 2
        assert stats["contradicted"] == 0

    def test_get_forgotten_below_threshold(self, tree):
        old_id = tree.add_leaf("stale finding", timestamp=time.time() - 1e8)
        recent_id = tree.add_leaf("fresh finding", timestamp=time.time())

        forgotten = tree.get_forgotten(threshold=0.5)
        forgotten_ids = {n.id for n in forgotten}

        assert old_id in forgotten_ids
        assert recent_id not in forgotten_ids

    def test_update_node_persists_metadata(self, tree):
        node_id = tree.add_leaf("content")
        node = tree.get_node(node_id)
        node.metadata["flag"] = True
        tree.update_node(node)

        reloaded = tree.get_node(node_id)
        assert reloaded.metadata == {"flag": True}


def test_level_config_consistency():
    # Every non-zero level has a window size and similarity threshold.
    for level in (1, 2, 3, 4):
        assert level in LEVEL_WINDOWS
        assert level in LEVEL_SIMILARITY_THRESHOLDS
