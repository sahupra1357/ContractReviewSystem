"""Pipeline worker — claims jobs from the Postgres queue and runs stages.

Run: python -m backend.worker           (loops; compose `worker` service)
     python -m backend.worker --once    (drain queue then exit; used in tests
                                         and local verification)

Stage handlers are registered by name; Phase 3+ adds mask/index/analyze.
Failures are never silent: status → failed_<stage>, error on the job, audit
event written (design doc §4).
"""

import argparse
import sys
import threading
import time
import traceback

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.analysis.service import run_analyze
from backend.audit import ActorType, record_event
from backend.db import get_sessionmaker
from backend.extraction.service import run_extract
from backend.knowledge.embedder import Embedder, get_embedder
from backend.knowledge.service import run_index
from backend.llm.base import LLMClient
from backend.llm.providers import get_llm_client
from backend.models import Document, DocumentStatus, Job
from backend.pii.service import run_pii_gate
from backend.storage import MaskedStorage, RawStorage, S3MaskedStorage, S3RawStorage

POLL_INTERVAL_SECONDS = 2.0

_embedder: Embedder | None = None
_llm: LLMClient | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = get_embedder()
    return _embedder


def _get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = get_llm_client()
    return _llm


def handle_extract(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    # Owns classify → OCR confidence gate → extracted | extract_hold (§3.2).
    run_extract(session, storage, document)


def handle_mask(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    run_pii_gate(session, storage, masked, document)


def handle_index(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    # deliberately does NOT pass the raw handle — index reads masked only
    run_index(session, masked, _get_embedder(), document)


def handle_analyze(
    session: Session, storage: RawStorage, masked: MaskedStorage, document: Document
) -> None:
    # masked-zone handle only — no provider ever sees raw text (invariant #1)
    run_analyze(session, masked, _get_llm(), document)


HANDLERS = {
    "extract": handle_extract,
    "mask": handle_mask,
    "index": handle_index,
    "analyze": handle_analyze,
}


# Human decisions are final for the pipeline: stages neither run on nor
# overwrite documents in these states (invariant #2 corollary — found by the
# Phase-7 LLM-down failure drill, where a failing analyze job stomped an
# approved document).
_TERMINAL_STATUSES = {DocumentStatus.approved, DocumentStatus.rejected}


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
    if DocumentStatus(document.status) in _TERMINAL_STATUSES:
        jobs.complete(job)
        record_event(
            session, actor_type=ActorType.system, actor_id=f"worker:{stage}",
            action="stage.skipped_terminal", object_type="document",
            object_id=document.id,
            detail={"stage": stage, "status": document.status, "job_id": job.id},
        )
        session.commit()
        return True
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
        if DocumentStatus(document.status) not in _TERMINAL_STATUSES:
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


INLINE_RETRY_SECONDS = 5.0
INLINE_RETRY_MAX_SECONDS = 60.0


def supervise(*, run_fn=None, sleep_fn=time.sleep, max_restarts: int | None = None) -> int:
    """Restart the loop if it raises, with backoff. Returns restarts performed.

    A standalone worker can let an exception kill the process — the container
    restarts it. An in-process loop cannot: the thread would die while the API
    kept answering /health, leaving a silently dead pipeline. Failures are
    always printed to stderr (Render/compose capture it) — never swallowed.
    """
    run_fn = run_fn or (lambda: run(False))
    delay = INLINE_RETRY_SECONDS
    restarts = 0
    while max_restarts is None or restarts < max_restarts:
        try:
            run_fn()
            return restarts   # only reachable if the loop ever returns
        except Exception:  # noqa: BLE001 — the supervisor must survive anything
            traceback.print_exc()
            print(
                f"[inline-worker] pipeline loop crashed; restarting in {delay:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            sleep_fn(delay)
            delay = min(delay * 2, INLINE_RETRY_MAX_SECONDS)
            restarts += 1
    return restarts


def start_inline(sessionmaker=None) -> threading.Thread:
    """Run the pipeline loop in a daemon thread inside the API process.

    For hosts with no worker tier (the free-tier demo). The stages, handlers and
    audit writes are byte-for-byte the ones the standalone worker runs — this
    changes only *where* the loop lives, never what it does.

    Two consequences worth knowing: the loop dies with the web process (so a
    host that idles the process out stops the pipeline until the next request),
    and orphaned `running` jobs are requeued at start, which assumes a single
    instance. Both are why this is off by default.
    """
    sessionmaker = sessionmaker or get_sessionmaker()
    with sessionmaker() as session:
        orphans = jobs.requeue_orphaned(session)
        for job in orphans:
            record_event(
                session, actor_type=ActorType.system, actor_id="worker:inline",
                action="job.requeued_orphaned", object_type="document",
                object_id=job.document_id,
                detail={"stage": job.stage, "job_id": job.id, "attempts": job.attempts},
            )
        session.commit()

    thread = threading.Thread(target=supervise, name="crs-inline-worker", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="drain queue and exit")
    run(parser.parse_args().once)
