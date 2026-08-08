"""Knowledge graph tables for HippoRAG-style associative retrieval.

Revision ID: 003
Revises: 002
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "kg_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_lower", sa.Text, sa.Computed("lower(name)", persisted=True), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False, server_default="UNKNOWN"),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("mention_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("metadata_json", JSONB, server_default="{}"),
        sa.UniqueConstraint("org_id", "name_lower", name="uq_entity_org_name"),
    )
    op.create_index("ix_kg_entities_org_name", "kg_entities", ["org_id", "name_lower"])
    op.execute(
        "CREATE INDEX ix_kg_entities_embedding_hnsw ON kg_entities "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.create_index("ix_kg_entities_mention_count", "kg_entities", ["org_id", sa.text("mention_count DESC")])

    op.create_table(
        "kg_triples",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_entity_id", UUID(as_uuid=True), sa.ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("predicate", sa.Text, nullable=False),
        sa.Column("object_entity_id", UUID(as_uuid=True), sa.ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_memory_id", UUID(as_uuid=True), sa.ForeignKey("memory_units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("predicate_embedding", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "org_id", "subject_entity_id", "predicate", "object_entity_id", "source_memory_id",
            name="uq_triple_source",
        ),
        sa.CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_triple_confidence"),
    )
    op.create_index("ix_kg_triples_subject", "kg_triples", ["org_id", "subject_entity_id"])
    op.create_index("ix_kg_triples_object", "kg_triples", ["org_id", "object_entity_id"])
    op.create_index("ix_kg_triples_source", "kg_triples", ["source_memory_id"])

    op.create_table(
        "kg_entity_mentions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", UUID(as_uuid=True), sa.ForeignKey("memory_units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mention_context", sa.Text, nullable=True),
        sa.Column("char_offset", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("entity_id", "memory_id", name="uq_entity_mention"),
    )
    op.create_index("ix_kg_mentions_entity", "kg_entity_mentions", ["entity_id"])
    op.create_index("ix_kg_mentions_memory", "kg_entity_mentions", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_kg_mentions_memory", table_name="kg_entity_mentions")
    op.drop_index("ix_kg_mentions_entity", table_name="kg_entity_mentions")
    op.drop_table("kg_entity_mentions")

    op.drop_index("ix_kg_triples_source", table_name="kg_triples")
    op.drop_index("ix_kg_triples_object", table_name="kg_triples")
    op.drop_index("ix_kg_triples_subject", table_name="kg_triples")
    op.drop_table("kg_triples")

    op.drop_index("ix_kg_entities_mention_count", table_name="kg_entities")
    op.drop_index("ix_kg_entities_embedding_hnsw", table_name="kg_entities")
    op.drop_index("ix_kg_entities_org_name", table_name="kg_entities")
    op.drop_table("kg_entities")
