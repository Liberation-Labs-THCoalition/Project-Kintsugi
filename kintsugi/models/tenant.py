"""Multi-tenancy SQLAlchemy models.

Provides the database-backed models for multi-tenant isolation:

- **Tenant**: Top-level tenant record with isolation mode and settings.
- **AuditLog**: Append-only log of tenant-scoped actions.
- **TenantScopedMixin**: Column mixin that enforces ``org_id`` filtering
  on all tenant-scoped queries.

The :class:`Organization` and :class:`MemoryUnit` models already carry an
``org_id`` FK in ``kintsugi.models.base``.  These new models complement
them with explicit tenant metadata and audit trails.

Note
----
SCHEMA and DATABASE isolation modes are documented but currently only
ROW_LEVEL isolation is implemented at the query level.  Schema-per-tenant
and database-per-tenant require infrastructure automation (see
``kintsugi.multitenancy.isolation``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from kintsugi.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class TenantScopedMixin:
    """Column mixin that adds an indexed ``org_id`` foreign key.

    Apply to any model that should be scoped to an organisation::

        class MyModel(Base, TenantScopedMixin):
            __tablename__ = "my_models"
            ...
    """

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class Tenant(Base):
    """Top-level tenant record.

    Each tenant maps 1:1 to an :class:`Organization` but stores
    multi-tenancy-specific metadata (isolation mode, slug, settings).

    Attributes
    ----------
    id:          Primary key (UUID).
    name:        Human-readable name.
    slug:        URL-safe short identifier (unique).
    isolation_mode:
        One of ``row_level``, ``schema``, ``database``.
    settings:    Arbitrary JSON configuration.
    created_at:  UTC creation timestamp.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    isolation_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="row_level"
    )
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Append-only audit log for tenant-scoped actions.

    Every significant operation (data access, config change, escalation)
    is recorded here for compliance and debugging.

    Attributes
    ----------
    id:          Primary key (UUID).
    org_id:      FK to ``organizations.id``.
    action:      Short verb describing the operation.
    actor:       Identifier of the user or system component that performed it.
    details:     Arbitrary JSON payload with operation-specific data.
    created_at:  UTC timestamp.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
