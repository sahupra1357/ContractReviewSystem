"""Audit event writer — the SOX-aware core.

Every stage transition, AI suggestion, and human action goes through
`record_event`. The audit_events table is append-only: a DB trigger rejects
UPDATE and DELETE (see alembic migration 0001), so history cannot be
rewritten even by the application role.
"""

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.db import Base


class ActorType(enum.StrEnum):
    human = "human"
    system = "system"


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType, name="actor_type"))
    actor_id: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(255))
    object_type: Mapped[str] = mapped_column(String(255))
    object_id: Mapped[str] = mapped_column(String(255))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def record_event(
    session: Session,
    *,
    actor_type: ActorType,
    actor_id: str,
    action: str,
    object_type: str,
    object_id: str,
    detail: dict[str, Any] | None = None,
    rationale: str | None = None,
) -> AuditEvent:
    """Append an audit event. Caller owns the transaction (commit with the
    action it records, so the event and the change are atomic)."""
    event = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        detail=detail,
        rationale=rationale,
    )
    session.add(event)
    return event
