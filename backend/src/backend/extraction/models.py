"""Extraction stage tables (design doc §3.2, §5.2).

extract_holds — OCR confidence flags awaiting human resolution. The fail-closed
twin of pii_holds: when every engine in the chain scores a page below the
confidence threshold, the document parks here instead of flowing toward the PII
gate, because low-confidence OCR mutates strings enough to slip PII past both
the master-table fuzzy match and the Presidio tripwire.
"""

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ExtractHoldStatus(enum.StrEnum):
    open = "open"
    accepted_best_effort = "accepted_best_effort"  # human kept the text → extracted
    rejected_scan = "rejected_scan"                # human rejected → failed_extract


class ExtractHold(Base):
    __tablename__ = "extract_holds"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # winning read, 0–1
    # per-engine attempts for this page: [{"engine","confidence","status"}]
    attempts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default=ExtractHoldStatus.open, index=True
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
