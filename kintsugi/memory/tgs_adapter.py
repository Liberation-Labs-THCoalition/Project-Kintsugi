"""Adapters wiring Kintsugi's real memory + knowledge-graph backends into
the TextStore / GraphStore protocols expected by tgs_verification.py.

TextGraphVerifier's protocols are synchronous (pure re-ranking logic, no
I/O of its own), but Kintsugi's database access is async-only. Both
adapters here follow the same pattern to bridge that gap: an async
classmethod (`search_async` / `load`) fetches everything needed for one
query/org up front from an async context, and the resulting object then
answers the synchronous Protocol methods purely from that in-memory
snapshot — no further I/O happens inside `search()` / `walk()` /
`get_entity_mentions()`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kintsugi.memory.cma_stage3 import ScoredResult, retrieve
from kintsugi.memory.tgs_verification import GraphEdge, GraphNode, GraphResult, TextGraphVerifier


class KintsugiTextStore:
    """Sync TextStore backed by a pre-fetched hybrid-retrieval snapshot."""

    def __init__(self, results: list[dict]):
        self._results = results

    def search(self, query: str, n_results: int = 10) -> list[dict]:
        return self._results[:n_results]

    @classmethod
    async def search_async(
        cls,
        session: AsyncSession,
        org_id: uuid.UUID,
        query: str,
        query_embedding: list[float] | None = None,
        n_results: int = 10,
    ) -> "KintsugiTextStore":
        """Run dense (pgvector) + lexical (tsvector) retrieval for one query
        and fuse via cma_stage3, returning a ready-to-use TextStore snapshot.
        """
        dense_results: list[ScoredResult] = []
        if query_embedding is not None:
            dense_stmt = text("""
                SELECT mu.id, mu.content, 1 - (me.embedding <=> :qemb) AS score
                FROM memory_embeddings me
                JOIN memory_units mu ON mu.id = me.memory_id
                WHERE mu.org_id = :org_id
                ORDER BY me.embedding <=> :qemb
                LIMIT :limit
            """).bindparams(org_id=org_id, qemb=str(query_embedding), limit=n_results * 2)
            rows = await session.execute(dense_stmt)
            dense_results = [
                ScoredResult(id=str(r[0]), content=r[1], score=float(r[2]), source="dense")
                for r in rows
            ]

        lexical_stmt = text("""
            SELECT mu.id, mu.content,
                   ts_rank(ml.tsv, plainto_tsquery('english', :query)) AS score
            FROM memory_lexical ml
            JOIN memory_units mu ON mu.id = ml.memory_id
            WHERE mu.org_id = :org_id
              AND ml.tsv @@ plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :limit
        """).bindparams(org_id=org_id, query=query, limit=n_results * 2)
        rows = await session.execute(lexical_stmt)
        lexical_results = [
            ScoredResult(id=str(r[0]), content=r[1], score=float(r[2]), source="lexical")
            for r in rows
        ]

        fused = retrieve(
            query=query,
            dense_results=dense_results,
            lexical_results=lexical_results,
            symbolic_results=(),
            n_results=n_results,
        )

        results = [
            {"id": r.id, "content": r.content, "score": r.score, "tags": []}
            for r in fused
        ]
        return cls(results)


class PostgresGraphStore:
    """Sync GraphStore backed by a pre-fetched knowledge-graph snapshot.

    Populated once per query/org via `load()` (async), then answers
    `walk()`/`get_entity_mentions()` purely from the in-memory graph —
    entity extraction from the query text is CPU-only (spaCy) so it's
    safe to run synchronously inside `walk()`.
    """

    def __init__(
        self,
        entity_types: dict[str, str],
        adjacency: dict[str, list[tuple[str, str, float]]],
        mentions: dict[str, list[str]],
    ):
        self._entity_types = entity_types
        self._adjacency = adjacency
        self._mentions = mentions

    @classmethod
    async def load(cls, session: AsyncSession, org_id: uuid.UUID) -> "PostgresGraphStore":
        entities_stmt = text(
            "SELECT name_lower, entity_type FROM kg_entities WHERE org_id = :org_id"
        ).bindparams(org_id=org_id)
        rows = await session.execute(entities_stmt)
        entity_types = {r[0]: r[1] for r in rows}

        triples_stmt = text("""
            SELECT s.name_lower, t.predicate, o.name_lower, t.confidence
            FROM kg_triples t
            JOIN kg_entities s ON s.id = t.subject_entity_id
            JOIN kg_entities o ON o.id = t.object_entity_id
            WHERE t.org_id = :org_id
        """).bindparams(org_id=org_id)
        rows = await session.execute(triples_stmt)
        adjacency: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        for subj, predicate, obj, confidence in rows:
            adjacency[subj].append((obj, predicate, confidence))
            adjacency[obj].append((subj, predicate, confidence))

        mentions_stmt = text("""
            SELECT e.name_lower, em.memory_id
            FROM kg_entity_mentions em
            JOIN kg_entities e ON e.id = em.entity_id
            WHERE e.org_id = :org_id
        """).bindparams(org_id=org_id)
        rows = await session.execute(mentions_stmt)
        mentions: dict[str, list[str]] = defaultdict(list)
        for name_lower, memory_id in rows:
            mentions[name_lower].append(str(memory_id))

        return cls(entity_types, dict(adjacency), dict(mentions))

    def walk(self, query: str, max_hops: int = 2, max_nodes: int = 20) -> GraphResult:
        from kintsugi.memory.kg_extractor import extract_entities

        seeds = [e.name.lower() for e in extract_entities(query)]
        seeds = [s for s in seeds if s in self._entity_types]

        visited: set[str] = set(seeds)
        edges: list[GraphEdge] = []
        frontier = list(seeds)

        for _ in range(max_hops):
            if len(visited) >= max_nodes:
                break
            next_frontier = []
            for node in frontier:
                for neighbor, predicate, confidence in self._adjacency.get(node, []):
                    edges.append(GraphEdge(
                        subject=node, predicate=predicate, object=neighbor, confidence=confidence,
                    ))
                    if neighbor not in visited and len(visited) < max_nodes:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
            frontier = next_frontier

        nodes = [
            GraphNode(entity=name, entity_type=self._entity_types.get(name, ""))
            for name in visited
        ]
        return GraphResult(nodes=nodes, edges=edges, visited_entities=visited)

    def get_entity_mentions(self, entity: str) -> list[str]:
        return self._mentions.get(entity.lower(), [])


async def create_kintsugi_verifier(
    session: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    query_embedding: list[float] | None = None,
    n_results: int = 10,
) -> TextGraphVerifier:
    """Build a fully-wired TextGraphVerifier for one query/org.

    Fetches both the text-retrieval snapshot and the knowledge-graph
    snapshot up front (async), then returns a verifier that re-ranks
    synchronously against both.
    """
    text_store = await KintsugiTextStore.search_async(
        session, org_id, query, query_embedding, n_results
    )
    graph_store = await PostgresGraphStore.load(session, org_id)

    return TextGraphVerifier(
        text_store=text_store,
        graph_store=graph_store,
    )
