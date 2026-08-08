"""Graph-based retrieval with Personalized PageRank and CatRAG edge weighting.

Built from Project Mnemosyne's hipporag-catrag-kg design spec (HippoRAG 2,
arXiv:2502.14802 + CatRAG, arXiv:2602.01965), adapted to Kintsugi's actual
async SQLAlchemy models.

At Kintsugi's target scale (hundreds to low thousands of entities per org),
loading the full adjacency matrix into memory and running dense PPR via
NumPy is fast enough — no need for a dedicated graph database.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kintsugi.models.knowledge_graph import KGEntity

logger = logging.getLogger(__name__)


@dataclass
class PPRConfig:
    """Configuration for Personalized PageRank."""
    alpha: float = 0.15        # Teleportation (restart) probability
    max_iterations: int = 50   # Maximum PPR iterations
    tolerance: float = 1e-6    # Convergence threshold
    top_k: int = 20            # Number of top entities to return


@dataclass
class GraphRetrievalResult:
    """A memory scored by graph-based retrieval."""
    memory_id: uuid.UUID
    score: float
    source_entities: list[str]  # Entity names that contributed to this score
    hops: int = 0  # Minimum graph distance from a seed node


async def find_seed_nodes(
    session: AsyncSession,
    org_id: uuid.UUID,
    query_entities: list[str],
    query_embedding: np.ndarray | None = None,
    fuzzy_threshold: float = 0.85,
) -> dict[uuid.UUID, float]:
    """Find KG nodes matching query entities. Returns {entity_id: seed_weight}.

    Strategy:
    1. Exact match on name_lower (weight 1.0)
    2. If query_embedding is provided and exact match fails, fall back to
       embedding similarity search (weight = similarity score)
    """
    seeds: dict[uuid.UUID, float] = {}

    for entity_name in query_entities:
        stmt = select(KGEntity.id).where(
            KGEntity.org_id == org_id,
            KGEntity.name_lower == entity_name.lower(),
        )
        result = await session.execute(stmt)
        row = result.first()
        if row:
            seeds[row[0]] = 1.0
            continue

        if query_embedding is not None:
            fuzzy_stmt = text("""
                SELECT id, 1 - (embedding <=> (:qemb)::vector) AS similarity
                FROM kg_entities
                WHERE org_id = :org_id
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> (:qemb)::vector
                LIMIT 3
            """).bindparams(org_id=org_id, qemb=str(query_embedding.tolist()))

            fuzzy_result = await session.execute(fuzzy_stmt)
            for frow in fuzzy_result:
                if frow[1] >= fuzzy_threshold:
                    seeds[frow[0]] = float(frow[1])

    return seeds


async def load_adjacency(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> tuple[dict[uuid.UUID, int], np.ndarray, list[dict]]:
    """Load the full adjacency structure for an organization's KG.

    Returns:
        - node_index: mapping from entity UUID to integer index
        - adjacency: N x N numpy adjacency matrix
        - edge_metadata: per-edge dicts (predicate, confidence, predicate_embedding)

    At our target scale (~1000 entities, ~5000 edges), loading the full
    adjacency into memory is fine.
    """
    stmt = select(KGEntity.id).where(KGEntity.org_id == org_id).order_by(KGEntity.id)
    result = await session.execute(stmt)
    entity_ids = [row[0] for row in result]

    node_index = {eid: i for i, eid in enumerate(entity_ids)}
    n = len(entity_ids)

    if n == 0:
        return node_index, np.zeros((0, 0)), []

    adjacency = np.zeros((n, n), dtype=np.float64)
    edge_meta: list[dict] = []

    triples_stmt = text("""
        SELECT subject_entity_id, object_entity_id, predicate,
               confidence, predicate_embedding
        FROM kg_triples
        WHERE org_id = :org_id
    """).bindparams(org_id=org_id)
    result = await session.execute(triples_stmt)

    for row in result:
        subj_idx = node_index.get(row[0])
        obj_idx = node_index.get(row[1])
        if subj_idx is not None and obj_idx is not None:
            adjacency[subj_idx, obj_idx] = row[3]
            adjacency[obj_idx, subj_idx] = row[3]  # undirected for PPR
            edge_meta.append({
                "subject_idx": subj_idx,
                "object_idx": obj_idx,
                "predicate": row[2],
                "confidence": row[3],
                "predicate_embedding": row[4],
            })

    return node_index, adjacency, edge_meta


def apply_catrag_weighting(
    adjacency: np.ndarray,
    edge_metadata: list[dict],
    query_embedding: np.ndarray,
    temperature: float = 0.1,
) -> np.ndarray:
    """Apply CatRAG-style query-adaptive edge weighting.

    For each edge, compute cosine similarity between the query embedding
    and the edge's predicate embedding, then softmax-scale the edge weight.
    Suppresses edges irrelevant to the current query, preventing PPR from
    drifting toward hub nodes along unrelated paths.
    """
    weighted = adjacency.copy()
    query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-9)

    for edge in edge_metadata:
        pred_emb = edge.get("predicate_embedding")
        if pred_emb is None:
            continue  # Keep original weight if no predicate embedding

        pred_vec = np.array(pred_emb, dtype=np.float64)
        pred_norm = pred_vec / (np.linalg.norm(pred_vec) + 1e-9)

        sim = float(np.dot(query_norm, pred_norm))

        scale = np.exp(sim / temperature) / np.exp(1.0 / temperature)
        scale = np.clip(scale, 0.01, 2.0)  # Prevent zeroing out or exploding

        i, j = edge["subject_idx"], edge["object_idx"]
        weighted[i, j] *= scale
        weighted[j, i] *= scale

    return weighted


def personalized_pagerank(
    adjacency: np.ndarray,
    seed_indices: dict[int, float],
    config: PPRConfig | None = None,
) -> np.ndarray:
    """Compute Personalized PageRank scores.

    Args:
        adjacency: Weighted adjacency matrix (N x N), optionally pre-weighted
            by CatRAG. Higher values = stronger connection.
        seed_indices: Dict mapping node index -> seed weight (teleportation bias).
        config: PPR hyperparameters.

    Returns:
        Array of PPR scores for each node (N,).
    """
    if config is None:
        config = PPRConfig()

    n = adjacency.shape[0]
    if n == 0:
        return np.array([])

    col_sums = adjacency.sum(axis=0)
    col_sums[col_sums == 0] = 1.0  # Avoid division by zero for dangling nodes
    transition = adjacency / col_sums

    personalization = np.zeros(n, dtype=np.float64)
    total_seed_weight = sum(seed_indices.values())
    if total_seed_weight > 0:
        for idx, weight in seed_indices.items():
            personalization[idx] = weight / total_seed_weight
    else:
        personalization[:] = 1.0 / n  # Uniform if no seeds

    scores = personalization.copy()
    alpha = config.alpha

    for iteration in range(config.max_iterations):
        prev = scores.copy()
        scores = (1 - alpha) * (transition @ scores) + alpha * personalization

        diff = np.abs(scores - prev).sum()
        if diff < config.tolerance:
            logger.debug("PPR converged in %d iterations (diff=%.2e)", iteration + 1, diff)
            break

    return scores


async def graph_retrieve(
    session: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    query_embedding: np.ndarray,
    config: PPRConfig | None = None,
    enable_catrag: bool = True,
    catrag_temperature: float = 0.1,
    spacy_model: str = "en_core_web_md",
) -> list[GraphRetrievalResult]:
    """Full graph-based retrieval pipeline.

    1. Extract entities from query
    2. Find seed nodes
    3. Load adjacency + apply CatRAG weighting
    4. Run PPR
    5. Map top entities to memories

    Returns:
        List of GraphRetrievalResult, sorted by score descending.
    """
    from kintsugi.memory.kg_extractor import extract_entities

    if config is None:
        config = PPRConfig()

    query_entities = extract_entities(query, spacy_model)
    entity_names = [e.name for e in query_entities]

    if not entity_names:
        logger.debug("No entities extracted from query, skipping graph retrieval")
        return []

    seeds = await find_seed_nodes(session, org_id, entity_names, query_embedding)
    if not seeds:
        logger.debug("No seed nodes found for entities: %s", entity_names)
        return []

    node_index, adjacency, edge_meta = await load_adjacency(session, org_id)
    if adjacency.size == 0:
        return []

    if enable_catrag and edge_meta:
        adjacency = apply_catrag_weighting(adjacency, edge_meta, query_embedding, catrag_temperature)

    seed_indices = {
        node_index[entity_id]: weight
        for entity_id, weight in seeds.items()
        if entity_id in node_index
    }

    ppr_scores = personalized_pagerank(adjacency, seed_indices, config)

    index_to_entity = {i: eid for eid, i in node_index.items()}
    top_indices = np.argsort(ppr_scores)[::-1][:config.top_k]

    top_entity_ids = []
    entity_scores: dict[uuid.UUID, float] = {}
    for idx in top_indices:
        score = ppr_scores[idx]
        if score < 1e-8:
            break
        eid = index_to_entity[idx]
        top_entity_ids.append(eid)
        entity_scores[eid] = float(score)

    if not top_entity_ids:
        return []

    mentions_stmt = text("""
        SELECT DISTINCT em.memory_id, em.entity_id, e.name
        FROM kg_entity_mentions em
        JOIN kg_entities e ON e.id = em.entity_id
        WHERE em.entity_id = ANY(:entity_ids)
        ORDER BY em.memory_id
    """).bindparams(entity_ids=top_entity_ids)
    result = await session.execute(mentions_stmt)

    memory_scores: dict[uuid.UUID, float] = {}
    memory_entities: dict[uuid.UUID, list[str]] = {}

    for row in result:
        mid, eid, ename = row[0], row[1], row[2]
        score = entity_scores.get(eid, 0.0)
        memory_scores[mid] = memory_scores.get(mid, 0.0) + score
        memory_entities.setdefault(mid, []).append(ename)

    results = []
    for mid, score in sorted(memory_scores.items(), key=lambda x: x[1], reverse=True):
        results.append(GraphRetrievalResult(
            memory_id=mid,
            score=score,
            source_entities=memory_entities.get(mid, []),
        ))

    return results
