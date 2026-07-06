"""Pipeline worker — claims jobs from the Postgres queue and runs stages.

Run: python -m backend.worker           (loops; compose `worker` service)
     python -m backend.worker --once    (drain queue then exit; used in tests
                                         and local verification)

Stage handlers are registered by name; Phase 3+ adds mask/index/analyze.
Failures are never silent: status → failed_<stage>, error on the job, audit
event written (design doc §4).
"""

import argparse
import json
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.audit import ActorType, record_event
from backend.db import get_sessionmaker
from backend.extraction.service import extract_document
from backend.knowledge.embedder import Embedder, get_embedder
from backend.knowledge.service import run_index
from backend.models import Document, DocumentStatus, Job
from backend.pii.service import run_pii_gate
from backend.storage import MaskedStorage, RawStorage, S3MaskedStorage, S3RawStorage

POLL_INTERVAL_SECONDS = 2.0

_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = get_embedder()
    return _embedder


def handle_extract(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    data = storage.get_raw(document.raw_key)
    artifact = extract_document(data, document.filename)
    # Extracted text is PRE-PII-GATE: raw zone only (invariant #1).
    artifact_key = f"{document.id}/extracted.json"
    storage.put_raw(artifact_key, json.dumps(artifact).encode(), "application/json")
    document.status = DocumentStatus.extracted
    jobs.enqueue(session, document_id=document.id, stage="mask")
    record_event(
        session,
        actor_type=ActorType.system,
        actor_id="worker:extract",
        action="stage.extracted",
        object_type="document",
        object_id=document.id,
        detail={
            "method": artifact["method"],
            "page_count": artifact["page_count"],
            "section_count": len(artifact["sections"]),
            "artifact_key": artifact_key,
        },
    )


def handle_mask(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    run_pii_gate(session, storage, masked, document)


def handle_index(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    # deliberately does NOT pass the raw handle — index reads masked only
    run_index(session, masked, _get_embedder(), document)


HANDLERS = {"extract": handle_extract, "mask": handle_mask, "index": handle_index}


def process_one(
    session: Session, storage: RawStorage, masked: MaskedStorage, *, stage: str
) -> bool:
    """Claim and run one job; returns False when the queue is empty."""
    job: Job | None = jobs.claim_next(session, stage=stage)
    if job is None:
        session.rollback()
        return False

    document = session.execute(
        select(Document).where(Document.id == job.document_id)
    ).scalar_one()
    try:
        HANDLERS[stage](session, storage, masked, document)
        jobs.complete(job)
        session.commit()
    except Exception as exc:  # noqa: BLE001 — worker must record any failure
        session.rollback()
        document = session.execute(
            select(Document).where(Document.id == job.document_id)
        ).scalar_one()
        job = session.get(Job, job.id)
        document.status = f"failed_{stage}"
        jobs.fail(job, f"{type(exc).__name__}: {exc}")
        record_event(
            session,
            actor_type=ActorType.system,
            actor_id=f"worker:{stage}",
            action=f"stage.failed_{stage}",
            object_type="document",
            object_id=document.id,
            detail={"error": f"{type(exc).__name__}: {exc}", "job_id": job.id},
        )
        session.commit()
    return True


def run(once: bool) -> None:
    sessionmaker = get_sessionmaker()
    storage = S3RawStorage()
    masked = S3MaskedStorage()
    stages = list(HANDLERS)
    while True:
        worked = False
        for stage in stages:
            with sessionmaker() as session:
                while process_one(session, storage, masked, stage=stage):
                    worked = True
        if once and not worked:
            return
        if not worked:
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="drain queue and exit")
    run(parser.parse_args().once)
