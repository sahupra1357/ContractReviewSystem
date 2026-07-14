"""Extraction stage: classify → extract → segment, with the OCR confidence
gate (design doc §3.2).

`extract_document` returns a RAW artifact (pre-PII-gate) — the worker stores it
in the raw zone only; the masking stage is its sole consumer. For scanned PDFs
the artifact carries per-page OCR provenance (engine, confidence, attempts).

`run_extract` is the worker entry point and mirrors `run_pii_gate`:
- clean read  → status `extracted`, mask job enqueued, audited;
- low OCR conf → status `extract_hold`, per-page holds recorded, NOTHING
  enqueued downstream — a human resolves (accept best-effort / reject scan);
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
from backend.extraction.models import ExtractHold, ExtractHoldStatus
from backend.extraction.segmenter import segment
from backend.models import Document, DocumentStatus
from backend.storage import RawStorage


def extract_document(
    data: bytes,
    filename: str,
    *,
    engine_chain: list[str] | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if engine_chain is None:
        engine_chain = [e.strip() for e in settings.ocr_engine_chain.split(",") if e.strip()]
    if threshold is None:
        threshold = settings.ocr_confidence_threshold

    kind = classify(data, filename)
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
            data, engine_chain=engine_chain, threshold=threshold
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


def run_extract(session: Session, storage: RawStorage, document: Document) -> None:
    data = storage.get_raw(document.raw_key)
    artifact = extract_document(data, document.filename)
    # Extracted text is PRE-PII-GATE: raw zone only (invariant #1). Stored even
    # on a hold, so an accepted best-effort read continues without re-OCR.
    artifact_key = f"{document.id}/extracted.json"
    storage.put_raw(artifact_key, json.dumps(artifact).encode(), "application/json")

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


def _record_hold(
    session: Session, document: Document, ocr: dict[str, Any], artifact_key: str
) -> None:
    document.status = DocumentStatus.extract_hold
    # Idempotent re-run: drop prior OPEN holds before re-recording this doc's.
    for stale in session.execute(
        select(ExtractHold).where(
            ExtractHold.document_id == document.id,
            ExtractHold.status == ExtractHoldStatus.open,
        )
    ).scalars():
        session.delete(stale)
    low = set(ocr["low_confidence_pages"])
    for page in ocr["pages"]:
        if page["page"] in low:
            session.add(
                ExtractHold(
                    document_id=document.id,
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
            "low_confidence_pages": ocr["low_confidence_pages"],
            "min_confidence": ocr["min_confidence"],
            "threshold": ocr["threshold"],
            "unavailable_engines": ocr["unavailable_engines"],
            "artifact_key": artifact_key,
        },
    )
