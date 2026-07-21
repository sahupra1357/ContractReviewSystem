"""Extraction stage: classify → extract → segment, with the OCR confidence
gate and batched, checkpointed large-document handling (design doc §3.2).

`extract_document` returns a RAW artifact (pre-PII-gate) — the worker stores it
in the raw zone only; the masking stage is its sole consumer. For scanned PDFs
the artifact carries per-page OCR provenance (engine, confidence, attempts).

Large documents (§3.2): the OCR path runs in bounded page batches so peak
memory is one batch of rasterized images, not the whole document. Each batch is
checkpointed to the raw zone (`{doc}/extract/batch-*.json`) so a crash/timeout
resumes mid-document. A document above `CRS_EXTRACT_MAX_PAGES` parks in
`extract_hold` (reason "oversized") for a human, instead of a worker consuming
unbounded time.

`run_extract` is the worker entry point and mirrors `run_pii_gate`:
- clean read   → status `extracted`, mask job enqueued, audited;
- low OCR conf → status `extract_hold` (reason low_confidence), per-page holds
  recorded, NOTHING enqueued downstream — a human resolves;
- oversized    → status `extract_hold` (reason oversized), one hold recorded,
  NOTHING enqueued — a human accepts (re-extract, cap lifted) or rejects;
- no engine produced any read → raised as a stage error (infra failure,
  `failed_extract`), not a human-resolvable hold.
"""

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.audit import ActorType, record_event
from backend.config import get_settings
from backend.extraction import fast_path
from backend.extraction.classifier import DocKind, classify
from backend.extraction.models import (
    ExtractHold,
    ExtractHoldReason,
    ExtractHoldStatus,
)
from backend.extraction.segmenter import segment
from backend.models import Document, DocumentStatus
from backend.storage import RawStorage

_PDF_KINDS = (DocKind.born_digital_pdf, DocKind.scanned_pdf)


class RawZoneCheckpoint:
    """Per-batch OCR checkpoint backed by the raw zone (design §3.2). Shards
    live pre-PII-gate (invariant #1) and are never read downstream — only this
    stage reads them, to resume a partially-OCR'd document."""

    def __init__(self, storage: RawStorage, document_id: str) -> None:
        self._storage = storage
        self._prefix = f"{document_id}/extract"

    def _key(self, start: int) -> str:
        return f"{self._prefix}/batch-{start:05d}.json"

    def has(self, start: int) -> bool:
        return self._storage.has_raw(self._key(start))

    def load(self, start: int) -> list:
        from backend.extraction.ocr_path import page_result_from_dict

        raw = json.loads(self._storage.get_raw(self._key(start)))
        return [page_result_from_dict(d) for d in raw]

    def save(self, start: int, batch: list) -> None:
        from backend.extraction.ocr_path import page_result_to_dict

        payload = json.dumps([page_result_to_dict(pr) for pr in batch]).encode()
        self._storage.put_raw(self._key(start), payload, "application/json")


def extract_document(
    data: bytes,
    filename: str,
    *,
    engine_chain: list[str] | None = None,
    threshold: float | None = None,
    batch_size: int | None = None,
    max_pages: int | None = None,
    checkpoint: Any | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if engine_chain is None:
        engine_chain = [e.strip() for e in settings.ocr_engine_chain.split(",") if e.strip()]
    if threshold is None:
        threshold = settings.ocr_confidence_threshold
    if batch_size is None:
        batch_size = settings.ocr_batch_size
    if max_pages is None:
        max_pages = settings.extract_max_pages

    kind = classify(data, filename)

    # Oversized guardrail (§3.2): read the page count cheaply (no rendering) and
    # halt before extraction if the document is too large. max_pages <= 0
    # disables the cap (used when a human has accepted an oversized document).
    if max_pages and kind in _PDF_KINDS:
        page_count = fast_path.pdf_page_count(data)
        if page_count > max_pages:
            return {
                "method": kind.value,
                "page_count": page_count,
                "pages": [],
                "full_text": "",
                "sections": [],
                "ocr": None,
                "oversized": True,
                "max_pages": max_pages,
            }

    ocr: dict[str, Any] | None = None
    if kind == DocKind.born_digital_pdf:
        pages = fast_path.extract_pdf(data)
    elif kind == DocKind.docx:
        pages = fast_path.extract_docx(data)
    elif kind == DocKind.plain_text:
        pages = fast_path.extract_plain(data)
    else:  # scanned → OCR chain (imported lazily: needs pypdfium2/engines)
        from backend.extraction.ocr_path import extract_scanned_pdf

        page_results = extract_scanned_pdf(
            data,
            engine_chain=engine_chain,
            threshold=threshold,
            batch_size=batch_size,
            checkpoint=checkpoint,
        )
        pages = [pr.page for pr in page_results]
        ocr = _summarize_ocr(page_results, engine_chain, threshold)

    full_text, sections = segment(pages)
    return {
        "method": kind.value,
        "page_count": len(pages),
        "pages": [asdict(p) for p in pages],
        "full_text": full_text,
        "sections": [asdict(s) for s in sections],
        "ocr": ocr,
        "oversized": False,
    }


def _summarize_ocr(page_results, engine_chain, threshold) -> dict[str, Any]:
    pages = [
        {
            "page": pr.page.number,
            "engine": pr.page.ocr_engine,
            "confidence": pr.page.ocr_confidence,
            "attempts": [asdict(a) for a in pr.attempts],
        }
        for pr in page_results
    ]
    scored = [p["confidence"] for p in pages if p["confidence"] is not None]
    unavailable = sorted(
        {a.engine for pr in page_results for a in pr.attempts if a.status == "unavailable"}
    )
    return {
        "engine_chain": engine_chain,
        "threshold": threshold,
        "pages": pages,
        "min_confidence": min(scored) if scored else None,
        "low_confidence_pages": [
            p["page"] for p in pages
            if p["confidence"] is not None and p["confidence"] < threshold
        ],
        "failed_pages": [p["page"] for p in pages if p["confidence"] is None],
        "unavailable_engines": unavailable,
    }


def _oversized_accepted(session: Session, document_id: str) -> bool:
    """True once a human has accepted an oversized document for processing —
    the extract re-run then lifts the page cap (§3.2)."""
    return (
        session.execute(
            select(ExtractHold).where(
                ExtractHold.document_id == document_id,
                ExtractHold.reason == ExtractHoldReason.oversized,
                ExtractHold.status == ExtractHoldStatus.accepted_best_effort,
            )
        ).first()
        is not None
    )


def run_extract(session: Session, storage: RawStorage, document: Document) -> None:
    data = storage.get_raw(document.raw_key)
    checkpoint = RawZoneCheckpoint(storage, document.id)
    # A human who accepted an oversized doc lifts the cap on the re-run.
    max_pages = 0 if _oversized_accepted(session, document.id) else None
    artifact = extract_document(
        data, document.filename, checkpoint=checkpoint, max_pages=max_pages
    )
    # Extracted text is PRE-PII-GATE: raw zone only (invariant #1). Stored even
    # on a hold, so an accepted best-effort read continues without re-OCR.
    artifact_key = f"{document.id}/extracted.json"
    storage.put_raw(artifact_key, json.dumps(artifact).encode(), "application/json")

    if artifact.get("oversized"):
        _record_oversized_hold(session, document, artifact, artifact_key)
        return

    ocr = artifact["ocr"]
    if ocr and ocr["failed_pages"]:
        # No engine produced a read for these pages — an infrastructure failure
        # (e.g. every configured engine unavailable), not a quality hold.
        raise RuntimeError(
            f"OCR produced no result for pages {ocr['failed_pages']} "
            f"(chain={ocr['engine_chain']}, unavailable={ocr['unavailable_engines']})"
        )

    if ocr and ocr["low_confidence_pages"]:
        _record_hold(session, document, ocr, artifact_key)
        return

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
            "ocr": _audit_ocr(ocr),
        },
    )


def _audit_ocr(ocr: dict[str, Any] | None) -> dict[str, Any] | None:
    if ocr is None:
        return None
    return {
        "min_confidence": ocr["min_confidence"],
        "threshold": ocr["threshold"],
        "engines_used": sorted(
            {p["engine"] for p in ocr["pages"] if p["engine"] is not None}
        ),
        "unavailable_engines": ocr["unavailable_engines"],
    }


def _drop_open_holds(session: Session, document_id: str) -> None:
    """Idempotent re-run: clear this doc's OPEN holds before re-recording."""
    for stale in session.execute(
        select(ExtractHold).where(
            ExtractHold.document_id == document_id,
            ExtractHold.status == ExtractHoldStatus.open,
        )
    ).scalars():
        session.delete(stale)


def _record_hold(
    session: Session, document: Document, ocr: dict[str, Any], artifact_key: str
) -> None:
    document.status = DocumentStatus.extract_hold
    _drop_open_holds(session, document.id)
    low = set(ocr["low_confidence_pages"])
    for page in ocr["pages"]:
        if page["page"] in low:
            session.add(
                ExtractHold(
                    document_id=document.id,
                    reason=ExtractHoldReason.low_confidence,
                    page_number=page["page"],
                    confidence=page["confidence"],
                    attempts=page["attempts"],
                    status=ExtractHoldStatus.open,
                )
            )
    record_event(
        session,
        actor_type=ActorType.system,
        actor_id="worker:extract",
        action="stage.extract_hold",
        object_type="document",
        object_id=document.id,
        detail={
            "reason": ExtractHoldReason.low_confidence.value,
            "low_confidence_pages": ocr["low_confidence_pages"],
            "min_confidence": ocr["min_confidence"],
            "threshold": ocr["threshold"],
            "unavailable_engines": ocr["unavailable_engines"],
            "artifact_key": artifact_key,
        },
    )


def _record_oversized_hold(
    session: Session, document: Document, artifact: dict[str, Any], artifact_key: str
) -> None:
    document.status = DocumentStatus.extract_hold
    _drop_open_holds(session, document.id)
    session.add(
        ExtractHold(
            document_id=document.id,
            reason=ExtractHoldReason.oversized,
            page_number=0,  # whole-document hold, not a single page
            confidence=None,
            attempts=None,
            status=ExtractHoldStatus.open,
        )
    )
    record_event(
        session,
        actor_type=ActorType.system,
        actor_id="worker:extract",
        action="stage.extract_hold",
        object_type="document",
        object_id=document.id,
        detail={
            "reason": ExtractHoldReason.oversized.value,
            "page_count": artifact["page_count"],
            "max_pages": artifact["max_pages"],
            "artifact_key": artifact_key,
        },
    )
