"""AI analysis results (design §5.1 `analyses`). Latest analysis per document
is replaced on re-run; the audit trail preserves history of runs."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    family: Mapped[str | None] = mapped_column(String(50), nullable=True)
    family_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON)   # all cited
    key_terms: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # approve | reject | changes_requested
    suggested_decision: Mapped[str] = mapped_column(String(30))
    rationale: Mapped[str] = mapped_column(Text)
    dropped_uncited: Mapped[int] = mapped_column(Integer, default=0)
    model_strong: Mapped[str] = mapped_column(String(100))
    model_fast: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
