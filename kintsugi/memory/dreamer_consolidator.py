"""Dreamer Consolidator — periodic temporal tree maintenance.

Vendored and adapted from Project Mnemosyne's h-mem-temporal component.
Runs during the dreamer's cycle (see kintsugi/memory/dreamer.py) to:
1. Consolidate new leaves into tree parents (bottom-up)
2. Detect reinforcement events (new results confirming old findings)
3. Detect contradiction events (new results opposing old findings)

Adaptation note: the original used a synchronous ``requests.post()`` call
to a local Ollama server for summarization/relationship checks. This
version calls Kintsugi's own ``AnthropicClient`` instead (no local model
dependency), which means every method that touches the LLM is async.
"""

from __future__ import annotations

import logging
import time

from kintsugi.cognition.llm_client import AnthropicClient
from kintsugi.cognition.model_router import ModelTier
from kintsugi.memory.temporal_tree import (
    LEVEL_SIMILARITY_THRESHOLDS,
    LEVEL_WINDOWS,
    TemporalTree,
    TreeNode,
)

logger = logging.getLogger(__name__)

CONSOLIDATION_PROMPT = """Summarize the following related memory entries into a single concise summary. Preserve key findings, dates, and conclusions. If entries contradict each other, note the contradiction.

Entries:
{entries}

Write a 2-4 sentence summary:"""

REINFORCEMENT_CHECK_PROMPT = """Given an existing finding and a new observation, determine their relationship.

Existing finding:
{existing}

New observation:
{new}

Respond with exactly one of:
- CONFIRMS: the new observation supports/replicates the existing finding
- CONTRADICTS: the new observation directly opposes the existing finding
- UNRELATED: the observations are about different topics

Response (one word):"""


def cosine_similarity_text(a: str, b: str) -> float:
    """Quick bag-of-words cosine similarity. No embeddings required."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    intersection = words_a & words_b
    if not words_a or not words_b:
        return 0.0
    return len(intersection) / (len(words_a) ** 0.5 * len(words_b) ** 0.5)


class DreamerConsolidator:
    """Runs temporal tree consolidation during dreamer cycles."""

    def __init__(
        self,
        tree: TemporalTree,
        llm_client: AnthropicClient,
        similarity_fn=None,
    ):
        self.tree = tree
        self.llm_client = llm_client
        self.similarity_fn = similarity_fn or cosine_similarity_text

    async def consolidate_level(self, source_level: int = 0) -> dict:
        """Consolidate nodes at source_level into parents at source_level + 1.

        Clusters nodes within the same time window that exceed the
        similarity threshold, then generates LLM summaries.
        """
        target_level = source_level + 1
        window_size = LEVEL_WINDOWS.get(target_level, LEVEL_WINDOWS[1])
        threshold = LEVEL_SIMILARITY_THRESHOLDS.get(target_level, 0.5)

        unconsolidated = self.tree.get_unconsolidated_leaves(source_level)
        if not unconsolidated:
            return {"consolidated": 0, "parents_created": 0}

        windows = self._partition_by_window(unconsolidated, window_size)

        parents_created = 0
        nodes_consolidated = 0

        for window_nodes in windows.values():
            clusters = self._cluster_by_similarity(window_nodes, threshold)

            for cluster in clusters:
                if len(cluster) < 2:
                    continue

                summary = await self._generate_summary(cluster)
                if summary:
                    self.tree.create_parent(cluster, summary, target_level)
                    parents_created += 1
                    nodes_consolidated += len(cluster)

        return {
            "source_level": source_level,
            "target_level": target_level,
            "consolidated": nodes_consolidated,
            "parents_created": parents_created,
            "remaining_orphans": len(unconsolidated) - nodes_consolidated,
        }

    async def check_reinforcements(self, lookback_hours: float = 4) -> dict:
        """Scan recent leaves for reinforcement/contradiction of older findings.

        Checks each new leaf against existing nodes at higher levels
        to detect replication or contradiction.
        """
        cutoff = time.time() - (lookback_hours * 3600)
        recent = self.tree.conn.execute("""
            SELECT id FROM tree_nodes
            WHERE level = 0 AND timestamp > ?
            ORDER BY timestamp
        """, (cutoff,)).fetchall()

        existing = self.tree.conn.execute("""
            SELECT id FROM tree_nodes
            WHERE level >= 1 AND contradicted_by IS NULL
            ORDER BY timestamp DESC
            LIMIT 50
        """).fetchall()

        results = {"confirmed": 0, "contradicted": 0, "checked": 0}

        for recent_row in recent:
            new_node = self.tree.get_node(recent_row[0])
            if not new_node:
                continue

            for existing_row in existing:
                old_node = self.tree.get_node(existing_row[0])
                if not old_node:
                    continue

                sim = self.similarity_fn(new_node.content, old_node.content)
                if sim < 0.3:
                    continue

                results["checked"] += 1
                relationship = await self._check_relationship(old_node, new_node)

                if relationship == "CONFIRMS":
                    self.tree.reinforce(old_node.id)
                    results["confirmed"] += 1
                    logger.info(
                        "Reinforced node %s (n_m now %s)",
                        old_node.id, old_node.reinforcement_count + 1,
                    )
                elif relationship == "CONTRADICTS":
                    self.tree.contradict(old_node.id, new_node.id)
                    results["contradicted"] += 1
                    logger.info(
                        "Contradicted node %s by %s", old_node.id, new_node.id,
                    )

        return results

    async def full_cycle(self) -> dict:
        """Run a complete dreamer consolidation cycle.

        1. Consolidate leaves -> day summaries
        2. Consolidate days -> week summaries (if enough accumulated)
        3. Check for reinforcements/contradictions
        """
        results = {}

        for level in range(3):
            r = await self.consolidate_level(level)
            if r["consolidated"] > 0:
                results[f"level_{level}_to_{level + 1}"] = r

        reinforcements = await self.check_reinforcements()
        results["reinforcements"] = reinforcements

        logger.info("Consolidation cycle complete: %s", results)
        return results

    def _partition_by_window(self, nodes: list[TreeNode],
                              window_size: float) -> dict[int, list[TreeNode]]:
        """Group nodes into time windows."""
        windows: dict[int, list[TreeNode]] = {}
        for node in nodes:
            window_key = int(node.timestamp // window_size)
            windows.setdefault(window_key, []).append(node)
        return windows

    def _cluster_by_similarity(self, nodes: list[TreeNode],
                                threshold: float) -> list[list[TreeNode]]:
        """Greedy clustering by pairwise similarity."""
        if len(nodes) <= 1:
            return [nodes]

        assigned = set()
        clusters = []

        for i, node_a in enumerate(nodes):
            if i in assigned:
                continue
            cluster = [node_a]
            assigned.add(i)

            for j, node_b in enumerate(nodes):
                if j in assigned:
                    continue
                sim = self.similarity_fn(node_a.content, node_b.content)
                if sim >= threshold:
                    cluster.append(node_b)
                    assigned.add(j)

            clusters.append(cluster)

        return clusters

    async def _generate_summary(self, nodes: list[TreeNode]) -> str | None:
        """Generate an LLM summary for a cluster of nodes."""
        entries = "\n---\n".join(
            f"[{i + 1}] {node.content[:500]}" for i, node in enumerate(nodes)
        )
        prompt = CONSOLIDATION_PROMPT.format(entries=entries)
        response = await self.llm_client.complete(
            prompt, tier=ModelTier.FAST, max_tokens=256, temperature=0.1,
        )
        return response.text.strip() if response.text else None

    async def _check_relationship(self, old: TreeNode, new: TreeNode) -> str:
        """Ask the LLM whether the new finding confirms/contradicts the old."""
        prompt = REINFORCEMENT_CHECK_PROMPT.format(
            existing=old.content[:500],
            new=new.content[:500],
        )
        response = await self.llm_client.complete(
            prompt, tier=ModelTier.FAST, max_tokens=50, temperature=0.0,
        )
        if response.text:
            text_upper = response.text.strip().upper()
            if "CONFIRMS" in text_upper:
                return "CONFIRMS"
            elif "CONTRADICTS" in text_upper:
                return "CONTRADICTS"
        return "UNRELATED"
