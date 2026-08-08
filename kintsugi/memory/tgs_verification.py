"""Text-Graph Synergy Verifier — bidirectional memory verification.

Vendored from Project Mnemosyne's tgs-verification component (unchanged —
pure Python, Protocol-based, no external dependencies).

Two retrieval channels that check each other's work:

Graph -> Text (verification):
  Graph entities vote on which text memories are relevant.
  A memory that mentions 3 entities from the graph walk scores
  higher than one that matches semantically but shares no entities.

Text -> Graph (completion):
  Text memories mention entities the graph walk missed (orphans).
  These orphan entities are "bridged" back into the graph context,
  recovering reasoning paths that pruning discarded.

The result: retrieval that's both precise (graph-verified) and
complete (text-recovered). See tgs_adapter.py for the Kintsugi-specific
TextStore/GraphStore implementations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# -- Interfaces --

class TextStore(Protocol):
    """Interface for text-based memory retrieval."""
    def search(self, query: str, n_results: int = 10) -> list[dict]:
        """Return memories as dicts with 'id', 'content', 'score', 'tags'."""
        ...


class GraphStore(Protocol):
    """Interface for knowledge graph queries."""
    def walk(self, query: str, max_hops: int = 2, max_nodes: int = 20) -> GraphResult:
        """Walk the graph from query entities. Return nodes and edges."""
        ...

    def get_entity_mentions(self, entity: str) -> list[str]:
        """Get memory IDs that mention this entity."""
        ...


@dataclass
class GraphNode:
    """A node in the knowledge graph."""
    entity: str
    entity_type: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    source_memory: str = ""


@dataclass
class GraphResult:
    """Result of a graph walk."""
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    visited_entities: set[str] = field(default_factory=set)


@dataclass
class VerifiedMemory:
    """A memory with verification metadata."""
    memory_id: str
    content: str
    text_score: float  # original semantic similarity score
    graph_score: float  # graph voting score
    combined_score: float  # final score after verification
    entity_overlap: list[str] = field(default_factory=list)
    bridged_entities: list[str] = field(default_factory=list)
    verification: str = ""  # "confirmed", "weakened", "bridged"


@dataclass
class VerificationReport:
    """Full verification report for a query."""
    query: str
    text_candidates: int
    graph_nodes: int
    verified_memories: list[VerifiedMemory]
    orphan_entities_found: int
    orphan_entities_bridged: int
    pruned_paths_recovered: int

    def summarize(self) -> str:
        parts = [
            f"TGS Verification: {self.query[:60]}",
            f"  Text candidates: {self.text_candidates}",
            f"  Graph nodes: {self.graph_nodes}",
            f"  Verified memories: {len(self.verified_memories)}",
            f"  Orphan entities bridged: {self.orphan_entities_bridged}",
            f"  Pruned paths recovered: {self.pruned_paths_recovered}",
        ]
        for vm in self.verified_memories[:5]:
            parts.append(f"  [{vm.verification}] score={vm.combined_score:.3f}: {vm.content[:80]}...")
        return "\n".join(parts)


# -- Core Verifier --

class TextGraphVerifier:
    """Bidirectional text-graph verification for memory retrieval.

    Args:
        text_store: Backend for semantic text search
        graph_store: Backend for knowledge graph queries
        graph_weight: How much graph voting affects final score (0-1)
        entity_boost: Score boost per overlapping entity
        orphan_threshold: Minimum text score for orphan entity bridging
    """

    def __init__(
        self,
        text_store: TextStore,
        graph_store: GraphStore,
        graph_weight: float = 0.4,
        entity_boost: float = 0.1,
        orphan_threshold: float = 0.3,
    ) -> None:
        self.text_store = text_store
        self.graph_store = graph_store
        self.graph_weight = graph_weight
        self.entity_boost = entity_boost
        self.orphan_threshold = orphan_threshold

    def retrieve(
        self,
        query: str,
        n_results: int = 10,
        max_hops: int = 2,
    ) -> VerificationReport:
        """Retrieve memories with bidirectional verification.

        1. Text retrieval -> candidate memories
        2. Graph walk -> related entities
        3. Graph votes on text (verification)
        4. Text bridges orphan entities (completion)
        5. Re-rank and return
        """
        # Step 1: Text retrieval
        text_results = self.text_store.search(query, n_results=n_results * 2)

        # Step 2: Graph walk
        graph_result = self.graph_store.walk(query, max_hops=max_hops)
        graph_entities = graph_result.visited_entities

        # Step 3: Graph -> Text verification (global voting)
        verified = self._graph_votes_on_text(text_results, graph_entities)

        # Step 4: Text -> Graph completion (orphan bridging)
        orphan_count, bridged_count, recovered_paths = self._bridge_orphans(
            verified, graph_entities, graph_result,
        )

        # Step 5: Re-rank by combined score
        verified.sort(key=lambda v: -v.combined_score)
        top_results = verified[:n_results]

        return VerificationReport(
            query=query,
            text_candidates=len(text_results),
            graph_nodes=len(graph_result.nodes),
            verified_memories=top_results,
            orphan_entities_found=orphan_count,
            orphan_entities_bridged=bridged_count,
            pruned_paths_recovered=recovered_paths,
        )

    def _graph_votes_on_text(
        self,
        text_results: list[dict],
        graph_entities: set[str],
    ) -> list[VerifiedMemory]:
        """Graph entities vote on text relevance.

        Each text memory gets a graph score based on how many
        graph-walked entities it mentions. More entity overlap
        = higher confidence the memory is truly relevant.
        """
        verified = []
        entity_lower = {e.lower() for e in graph_entities}

        for result in text_results:
            content = result.get("content", "")
            content_lower = content.lower()
            text_score = result.get("score", 0.5)

            # Count entity overlap
            overlap = [
                e for e in graph_entities
                if e.lower() in content_lower
            ]

            # Graph score: entity coverage
            if entity_lower:
                coverage = len(overlap) / len(entity_lower)
            else:
                coverage = 0.0

            graph_score = coverage + len(overlap) * self.entity_boost

            # Combined score
            combined = (
                text_score * (1 - self.graph_weight)
                + graph_score * self.graph_weight
            )

            # Verification status
            if len(overlap) >= 2:
                verification = "confirmed"
            elif len(overlap) == 1:
                verification = "partial"
            elif text_score > 0.7:
                verification = "text_only"
            else:
                verification = "weakened"

            verified.append(VerifiedMemory(
                memory_id=result.get("id", ""),
                content=content,
                text_score=text_score,
                graph_score=graph_score,
                combined_score=combined,
                entity_overlap=overlap,
                verification=verification,
            ))

        return verified

    def _bridge_orphans(
        self,
        verified: list[VerifiedMemory],
        graph_entities: set[str],
        graph_result: GraphResult,
    ) -> tuple[int, int, int]:
        """Text -> Graph: bridge orphan entities.

        Find entities mentioned in high-scoring text memories
        that were NOT in the graph walk (orphans). These are
        entities the graph pruned that the text suggests are relevant.
        """
        # Collect all entities mentioned in text but not in graph
        graph_lower = {e.lower() for e in graph_entities}
        orphan_entities: set[str] = set()
        recovered_paths = 0

        for vm in verified:
            if vm.text_score < self.orphan_threshold:
                continue

            # Extract entities from text (simple: look for capitalized phrases)
            words = vm.content.split()
            for i, word in enumerate(words):
                if word and word[0].isupper() and len(word) > 2:
                    entity = word.strip(".,;:!?\"'()")
                    if entity.lower() not in graph_lower and len(entity) > 2:
                        orphan_entities.add(entity)

        # Bridge orphans: check if they connect back to graph entities
        bridged = set()
        for orphan in orphan_entities:
            try:
                mentions = self.graph_store.get_entity_mentions(orphan)
                if mentions:
                    bridged.add(orphan)
                    recovered_paths += 1

                    # Boost memories that mention bridged entities
                    for vm in verified:
                        if orphan.lower() in vm.content.lower():
                            vm.bridged_entities.append(orphan)
                            vm.combined_score += self.entity_boost
                            if vm.verification == "weakened":
                                vm.verification = "bridged"
            except Exception:
                pass

        return len(orphan_entities), len(bridged), recovered_paths
