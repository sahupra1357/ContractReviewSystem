"""Ingestion core — every source lands here (design doc §3.1).

One path for all connectors: SHA-256 → dedup → raw store → registry →
enqueue extract job → audit. Duplicates are skipped and audited, never
reprocessed (idempotency: re-sending the same bytes cannot create a second
document or job).
"""

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.audit import ActorType, record_event
from backend.models import Document, DocumentStatus
from backend.storage import RawStorage


@dataclass
class IngestResult:
    document_id: str
    duplicate: bool
    sha256: str


def ingest_document(
    session: Session,
    storage: RawStorage,
    *,
    source: str,
    filename: str,
    data: bytes,
    actor_id: str,
    content_type: str | None = None,
    source_ref: str | None = None,
    urgency: dict | None = None,
) -> IngestResult:
    """Land one document. Caller owns the transaction (commit after)."""
    sha256 = hashlib.sha256(data).hexdigest()

    existing = session.execute(
        select(Document).where(Document.content_sha256 == sha256)
    ).scalar_one_or_none()
    if existing is not None:
        record_event(
            session,
            actor_type=ActorType.human if source == "upload" else ActorType.system,
            actor_id=actor_id,
            action="ingest.duplicate_skipped",
            object_type="document",
            object_id=existing.id,
            detail={"source": source, "filename": filename, "sha256": sha256},
        )
        return IngestResult(document_id=existing.id, duplicate=True, sha256=sha256)

    document = Document(
        source=source,
        source_ref=source_ref,
        filename=filename,
        content_sha256=sha256,
        size_bytes=len(data),
        content_type=content_type,
        status=DocumentStatus.ingested,
        urgency=urgency,
        uploaded_by=actor_id,
        raw_key="",  # set below once the id exists
    )
    session.add(document)
    session.flush()  # assign document.id

    document.raw_key = f"{document.id}/{filename}"
    storage.put_raw(document.raw_key, data, content_type)

    jobs.enqueue(session, document_id=document.id, stage="extract")

    record_event(
        session,
        actor_type=ActorType.human if source == "upload" else ActorType.system,
        actor_id=actor_id,
        action="ingest.landed",
        object_type="document",
        object_id=document.id,
        detail={
            "source": source,
            "filename": filename,
            "sha256": sha256,
            "size_bytes": len(data),
            "raw_key": document.raw_key,
        },
    )
    return IngestResult(document_id=document.id, duplicate=False, sha256=sha256)
