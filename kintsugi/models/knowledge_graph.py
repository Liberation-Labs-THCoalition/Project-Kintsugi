"""Knowledge graph ORM models — associative memory retrieval (HippoRAG-style).

Three tables layered on top of the existing memory schema:

- **kg_entities**: canonical entity nodes (PERSON, ORG, GPE, ...) per org.
- **kg_triples**: directed (subject, predicate, object) edges with provenance.
- **kg_entity_mentions**: links entities to the memories where they appear.

Additive only — no changes to existing tables. See kintsugi/memory/kg_extractor.py,
kg_store.py, and kg_retrieval.py for the extraction/persistence/PPR pipeline built
on top of these models.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kintsugi.db import Base
from kintsugi.models.base import _utcnow, _uuid


class KGEntity(Base):
    """Canonical entity node in the knowledge graph."""
    __tablename__ = "kg_entities"
    __table_args__ = (
        UniqueConstraint("org_id", "name_lower", name="uq_entity_org_name"),
        Index("ix_kg_entities_org_name", "org_id", "name_lower"),
        Index("ix_kg_entities_mention_count", "org_id", "mention_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_lower: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    embedding = mapped_column(Vector(768), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    outgoing_triples: Mapped[list["KGTriple"]] = relationship(
        foreign_keys="KGTriple.subject_entity_id", back_populates="subject"
    )
    incoming_triples: Mapped[list["KGTriple"]] = relationship(
        foreign_keys="KGTriple.object_entity_id", back_populates="object"
    )
    mentions: Mapped[list["KGEntityMention"]] = relationship(back_populates="entity")


class KGTriple(Base):
    """Directed edge in the knowledge graph: (subject, predicate, object)."""
    __tablename__ = "kg_triples"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "subject_entity_id", "predicate", "object_entity_id", "source_memory_id",
            name="uq_triple_source",
        ),
        CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_triple_confidence"),
        Index("ix_kg_triples_subject", "org_id", "subject_entity_id"),
        Index("ix_kg_triples_object", "org_id", "object_entity_id"),
        Index("ix_kg_triples_source", "source_memory_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_units.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    predicate_embedding = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    subject: Mapped["KGEntity"] = relationship(
        foreign_keys=[subject_entity_id], back_populates="outgoing_triples"
    )
    object: Mapped["KGEntity"] = relationship(
        foreign_keys=[object_entity_id], back_populates="incoming_triples"
    )


class KGEntityMention(Base):
    """Links an entity to a memory where it was mentioned."""
    __tablename__ = "kg_entity_mentions"
    __table_args__ = (
        UniqueConstraint("entity_id", "memory_id", name="uq_entity_mention"),
        Index("ix_kg_mentions_entity", "entity_id"),
        Index("ix_kg_mentions_memory", "memory_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_units.id", ondelete="CASCADE"), nullable=False
    )
    mention_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entity: Mapped["KGEntity"] = relationship(back_populates="mentions")
