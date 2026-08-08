"""Tests for kintsugi.memory.dreamer_consolidator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from kintsugi.memory.dreamer_consolidator import DreamerConsolidator, cosine_similarity_text
from kintsugi.memory.temporal_tree import TemporalTree


@pytest.fixture
def tree():
    t = TemporalTree(":memory:")
    yield t
    t.close()


def _mock_llm(text: str) -> AsyncMock:
    client = AsyncMock()
    response = AsyncMock()
    response.text = text
    client.complete.return_value = response
    return client


class TestCosineSimilarityText:
    def test_identical_text_scores_one(self):
        assert cosine_similarity_text("hello world", "hello world") == pytest.approx(1.0)

    def test_disjoint_text_scores_zero(self):
        assert cosine_similarity_text("apples oranges", "trucks planes") == 0.0

    def test_empty_text_scores_zero(self):
        assert cosine_similarity_text("", "something") == 0.0


class TestConsolidateLevel:
    @pytest.mark.asyncio
    async def test_no_unconsolidated_leaves_is_noop(self, tree):
        llm = _mock_llm("summary")
        consolidator = DreamerConsolidator(tree, llm)
        result = await consolidator.consolidate_level(0)
        assert result == {"consolidated": 0, "parents_created": 0}
        llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_similar_nodes_get_consolidated(self, tree):
        now = time.time()
        tree.add_leaf("the budget was approved", timestamp=now)
        tree.add_leaf("the budget was approved yesterday", timestamp=now + 10)

        llm = _mock_llm("Budget approved.")
        consolidator = DreamerConsolidator(
            tree, llm, similarity_fn=lambda a, b: 1.0,  # force same cluster
        )

        result = await consolidator.consolidate_level(0)

        assert result["parents_created"] == 1
        assert result["consolidated"] == 2
        llm.complete.assert_awaited()

    @pytest.mark.asyncio
    async def test_dissimilar_nodes_stay_unconsolidated(self, tree):
        now = time.time()
        tree.add_leaf("about the budget", timestamp=now)
        tree.add_leaf("about the weather", timestamp=now + 10)

        llm = _mock_llm("summary")
        consolidator = DreamerConsolidator(
            tree, llm, similarity_fn=lambda a, b: 0.0,  # force separate clusters
        )

        result = await consolidator.consolidate_level(0)

        assert result["parents_created"] == 0
        llm.complete.assert_not_called()


class TestCheckReinforcements:
    @pytest.mark.asyncio
    async def test_confirms_reinforces_existing_node(self, tree):
        now = time.time()
        # Timestamp well outside the 100h lookback window used below, so the
        # old leaf itself isn't also picked up by the "recent" leaf query.
        old_leaf = tree.get_node(tree.add_leaf("old finding", timestamp=now - 400_000))
        old_node_id = tree.create_parent([old_leaf], "established finding", level=1)
        tree.add_leaf("new finding replicates old finding", timestamp=now)

        llm = _mock_llm("CONFIRMS")
        consolidator = DreamerConsolidator(tree, llm, similarity_fn=lambda a, b: 1.0)

        result = await consolidator.check_reinforcements(lookback_hours=100)

        assert result["confirmed"] == 1
        assert tree.get_node(old_node_id).reinforcement_count == 1

    @pytest.mark.asyncio
    async def test_contradicts_marks_node_contradicted(self, tree):
        now = time.time()
        # Timestamp well outside the 100h lookback window used below, so the
        # old leaf itself isn't also picked up by the "recent" leaf query.
        old_leaf = tree.get_node(tree.add_leaf("old finding", timestamp=now - 400_000))
        old_node_id = tree.create_parent([old_leaf], "established finding", level=1)
        tree.add_leaf("new finding opposes old finding", timestamp=now)

        llm = _mock_llm("CONTRADICTS")
        consolidator = DreamerConsolidator(tree, llm, similarity_fn=lambda a, b: 1.0)

        result = await consolidator.check_reinforcements(lookback_hours=100)

        assert result["contradicted"] == 1
        assert tree.get_node(old_node_id).contradicted_by is not None

    @pytest.mark.asyncio
    async def test_low_similarity_skips_llm_check(self, tree):
        now = time.time()
        # Timestamp well outside the 100h lookback window used below, so the
        # old leaf itself isn't also picked up by the "recent" leaf query.
        old_leaf = tree.get_node(tree.add_leaf("old finding", timestamp=now - 400_000))
        tree.create_parent([old_leaf], "established finding", level=1)
        tree.add_leaf("unrelated content", timestamp=now)

        llm = _mock_llm("CONFIRMS")
        consolidator = DreamerConsolidator(tree, llm, similarity_fn=lambda a, b: 0.0)

        result = await consolidator.check_reinforcements(lookback_hours=100)

        assert result["checked"] == 0
        llm.complete.assert_not_called()


class TestFullCycle:
    @pytest.mark.asyncio
    async def test_runs_without_error_on_empty_tree(self, tree):
        llm = _mock_llm("summary")
        consolidator = DreamerConsolidator(tree, llm)
        result = await consolidator.full_cycle()
        assert "reinforcements" in result
