"""PII gate tables (design doc §3.3, §5.2) — restricted data.

pii_known_entities — the master table: the ONLY masking authority.
pii_entity_map    — what was masked where (layer-tagged); reveal is
                    RBAC-gated and audited (Phase 6 UI).
pii_holds         — fail-closed tripwire flags awaiting human resolution.

In production these live in a restricted schema with separate grants; the
POC keeps them in the app database and documents the gap (G3 report).
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class PiiEntityType(enum.StrEnum):
    person = "PERSON"
    org = "ORG"
    account = "ACCOUNT"
    address = "ADDRESS"
    email = "EMAIL"
    phone = "PHONE"
    other = "OTHER"


class KnownEntity(Base):
    __tablename__ = "pii_known_entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    value: Mapped[str] = mapped_column(String(500), unique=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EntityMapRow(Base):
    __tablename__ = "pii_entity_map"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    placeholder: Mapped[str] = mapped_column(String(50))     # e.g. "[PERSON-1]"
    entity_value: Mapped[str] = mapped_column(String(500))   # original text
    entity_type: Mapped[str] = mapped_column(String(30))
    layer: Mapped[str] = mapped_column(String(20))           # "registered" | "tripwire-added"
    occurrences: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HoldStatus(enum.StrEnum):
    open = "open"
    added_to_master = "added_to_master"
    dismissed = "dismissed"


class PiiHold(Base):
    __tablename__ = "pii_holds"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    flag_type: Mapped[str] = mapped_column(String(50))       # detector entity type
    span_text: Mapped[str] = mapped_column(String(500))
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    detector: Mapped[str] = mapped_column(String(50))        # "presidio" | "regex:<name>"
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=HoldStatus.open, index=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
