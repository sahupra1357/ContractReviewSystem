"""Document registry and pipeline job queue (design doc §5.1).

Document.status follows the workflow state machine (§4):
    ingested → extracted → masking → (masked | pii_hold) → indexed
    → analyzed → in_review → approved | rejected | changes_requested
Failures land in failed_<stage>. Transitions to approved/rejected exist
ONLY on the human-decision API path (invariant #2) — pipeline code must
never set them.
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class DocumentStatus(enum.StrEnum):
    ingested = "ingested"
    extract_hold = "extract_hold"  # OCR confidence below threshold — human resolves (§3.2)
    failed_extract = "failed_extract"  # scan rejected at an extract_hold, or extract error
    extracted = "extracted"
    masking = "masking"
    masked = "masked"
    pii_hold = "pii_hold"
    indexed = "indexed"
    analyzed = "analyzed"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(100))  # connector name, e.g. "upload"
    source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filename: Mapped[str] = mapped_column(String(1000))
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # str, not DocumentStatus enum column: statuses grow phase by phase
    status: Mapped[str] = mapped_column(String(50), default=DocumentStatus.ingested, index=True)
    urgency: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(255))
    raw_key: Mapped[str] = mapped_column(String(1200))  # object key in the raw bucket
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class JobState(enum.StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(50))  # e.g. "extract"
    state: Mapped[str] = mapped_column(String(20), default=JobState.pending, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
