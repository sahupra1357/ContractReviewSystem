"""Knowledge & index tables (design doc §3.4, §5.1) — MASKED data only.

Everything here is downstream of the PII gate: chunk text comes exclusively
from masked artifacts. Graph-lite entities reference master-table ids —
never raw values — so cross-contract joins (same party across contracts)
work without exposing PII outside the restricted entity map.
"""

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base

EMBEDDING_DIM = 1024  # BGE-M3 dense vectors


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    section_id: Mapped[str] = mapped_column(String(50))
    part: Mapped[int] = mapped_column(Integer, default=0)  # >0 when a section is split
    heading: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)               # MASKED text
    chunk_sha256: Mapped[str] = mapped_column(String(64), index=True)
    start: Mapped[int] = mapped_column(Integer)           # offsets into masked_text
    end: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EmbeddingCache(Base):
    """Embeddings keyed by content hash — re-ingests and repeated template
    text never recompute (design §3.8)."""

    __tablename__ = "embedding_cache"

    chunk_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GraphEntity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(30))          # party | term | contract
    ref: Mapped[str] = mapped_column(String(500))          # placeholder or term value
    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    master_entity_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True             # → pii_known_entities.id
    )
    section_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GraphRelationship(Base):
    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    from_entity_id: Mapped[str] = mapped_column(String(32))
    rel_type: Mapped[str] = mapped_column(String(50))      # HAS_PARTY | HAS_TERM
    to_entity_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
