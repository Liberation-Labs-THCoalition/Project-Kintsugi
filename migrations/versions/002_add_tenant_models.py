"""Add Tenant and AuditLog tables for multi-tenancy.

Revision ID: 002
Revises: 001
Create Date: 2026-02-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "isolation_mode",
            sa.String(32),
            nullable=False,
            server_default="row_level",
        ),
        sa.Column("settings", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(256), nullable=True),
        sa.Column("details", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_org_created", "audit_logs", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_org_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("tenants")
