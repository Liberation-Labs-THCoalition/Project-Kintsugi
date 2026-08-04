"""Persist extracted entities and triples to PostgreSQL.

Built from Project Mnemosyne's hipporag-catrag-kg design spec, adapted to
use Kintsugi's actual ORM models (kintsugi.models.knowledge_graph) instead
of bare table references.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kintsugi.models.knowledge_graph import KGEntity, KGEntityMention, KGTriple

logger = logging.getLogger(__name__)


async def upsert_entity(
    session: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    entity_type: str,
    embedding: list[float] | None = None,
) -> uuid.UUID:
    """Insert or update a KG entity. Returns the entity ID.

    Uses PostgreSQL ON CONFLICT for atomic upsert. If the entity already
    exists (same org + lowercase name), updates last_seen and increments
    mention_count.
    """
    # name_lower is a Postgres GENERATED ALWAYS column (lower(name)) — it
    # must not appear in the insert column list at all, not even with the
    # "correct" value; Postgres computes and persists it itself.
    stmt = pg_insert(KGEntity.__table__).values(
        org_id=org_id,
        name=name,
        entity_type=entity_type,
        embedding=embedding,
    ).on_conflict_do_update(
        constraint="uq_entity_org_name",
        set_={
            "last_seen": pg_insert(KGEntity.__table__).excluded.last_seen,
            "mention_count": KGEntity.__table__.c.mention_count + 1,
            "entity_type": entity_type,
        },
    ).returning(KGEntity.__table__.c.id)

    result = await session.execute(stmt)
    return result.scalar_one()


async def insert_triple(
    session: AsyncSession,
    org_id: uuid.UUID,
    subject_entity_id: uuid.UUID,
    predicate: str,
    object_entity_id: uuid.UUID,
    source_memory_id: uuid.UUID,
    confidence: float = 1.0,
    predicate_embedding: list[float] | None = None,
) -> uuid.UUID | None:
    """Insert a KG triple. Returns the triple ID, or None if duplicate."""
    stmt = pg_insert(KGTriple.__table__).values(
        org_id=org_id,
        subject_entity_id=subject_entity_id,
        predicate=predicate,
        object_entity_id=object_entity_id,
        source_memory_id=source_memory_id,
        confidence=confidence,
        predicate_embedding=predicate_embedding,
    ).on_conflict_do_nothing(
        constraint="uq_triple_source",
    ).returning(KGTriple.__table__.c.id)

    result = await session.execute(stmt)
    row = result.first()
    return row[0] if row else None


async def link_entity_to_memory(
    session: AsyncSession,
    entity_id: uuid.UUID,
    memory_id: uuid.UUID,
    mention_context: str | None = None,
    char_offset: int | None = None,
) -> None:
    """Record that an entity was mentioned in a specific memory."""
    stmt = pg_insert(KGEntityMention.__table__).values(
        entity_id=entity_id,
        memory_id=memory_id,
        mention_context=mention_context,
        char_offset=char_offset,
    ).on_conflict_do_nothing(constraint="uq_entity_mention")

    await session.execute(stmt)


async def process_memory_for_kg(
    session: AsyncSession,
    org_id: uuid.UUID,
    memory_id: uuid.UUID,
    content: str,
    embedder=None,
    spacy_model: str = "en_core_web_md",
) -> dict:
    """Full pipeline: extract entities and triples from a memory, persist to KG.

    Args:
        session: Active database session.
        org_id: Organization ID (for isolation).
        memory_id: The memory_units.id being processed.
        content: The memory text content.
        embedder: Optional EmbeddingProvider for entity/predicate embeddings.
        spacy_model: spaCy model name for extraction.

    Returns:
        Summary dict with counts of entities and triples created.
    """
    from kintsugi.memory.kg_extractor import run_extraction

    result = run_extraction(content, spacy_model)

    entity_id_map: dict[str, uuid.UUID] = {}
    for entity in result.entities:
        emb = None
        if embedder is not None:
            emb_array = await embedder.embed(entity.name)
            emb = emb_array.tolist() if hasattr(emb_array, "tolist") else list(emb_array)

        eid = await upsert_entity(
            session, org_id, entity.name, entity.entity_type, emb
        )
        entity_id_map[entity.name] = eid

        await link_entity_to_memory(
            session, eid, memory_id, entity.context, entity.char_start
        )

    triples_created = 0
    for triple in result.triples:
        subj_id = entity_id_map.get(triple.subject)
        obj_id = entity_id_map.get(triple.object)
        if subj_id and obj_id:
            pred_emb = None
            if embedder is not None:
                pred_array = await embedder.embed(triple.predicate)
                pred_emb = pred_array.tolist() if hasattr(pred_array, "tolist") else list(pred_array)

            tid = await insert_triple(
                session, org_id, subj_id, triple.predicate, obj_id,
                memory_id, triple.confidence, pred_emb
            )
            if tid is not None:
                triples_created += 1

    await session.flush()

    return {
        "entities_processed": len(result.entities),
        "triples_created": triples_created,
        "entity_names": [e.name for e in result.entities],
    }
