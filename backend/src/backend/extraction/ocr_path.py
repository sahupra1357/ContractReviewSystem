"""OCR path — confidence-gated multi-engine chain (design doc §3.2).

For each rasterized page we walk the configured engine chain
(Tesseract → PaddleOCR → EasyOCR → Docling by default): a page scoring at or
above the confidence threshold stops the walk; a page below it falls through
to the next engine, and the highest-confidence read wins. Engines whose
library isn't installed are skipped (reported per page). `run_extract`
(service.py) turns a low-confidence page into an `extract_hold`.

**Large documents (design §3.2):** pages are processed in bounded batches of
`batch_size` — rasterize a batch → walk the chain → free the images → next
batch, so peak memory is one batch of page images, not the whole document.
Each completed batch is handed to an optional `Checkpoint`; on a re-run, a
batch whose checkpoint already exists is loaded instead of re-OCR'd, so a
crash/timeout resumes from the first missing batch rather than page 1.

Pages are rasterized with pypdfium2 (no system poppler needed). The chain walk
is a pure function (`walk_chain`) so it is unit-tested with fake engines and no
real OCR binary or scanned PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pypdfium2 as pdfium

from backend.extraction.fast_path import Page
from backend.extraction.ocr_engines import EngineUnavailable, OcrEngine, build_chain

# 300 dpi read quality, capped so oversized scans don't blow up memory.
_TARGET_WIDTH_PX = 2400


@dataclass
class Attempt:
    engine: str
    confidence: float | None  # None when the engine was unavailable or errored
    status: str  # "ok" | "unavailable" | "error"


@dataclass
class PageResult:
    page: Page
    attempts: list[Attempt]


class Checkpoint(Protocol):
    """Per-batch persistence for resumable OCR (design §3.2). Implemented over
    the raw zone in service.py; kept a Protocol here so `extract_scanned_pdf`
    stays decoupled from storage and testable with a fake."""

    def has(self, start: int) -> bool: ...

    def load(self, start: int) -> list[PageResult]: ...

    def save(self, start: int, batch: list[PageResult]) -> None: ...


def walk_chain(
    images: list[Any],
    engines: list[OcrEngine],
    threshold: float,
    *,
    page_offset: int = 0,
) -> list[PageResult]:
    """Run the engine chain over pre-rasterized page images. Pure and
    engine-agnostic: `images` are opaque to this function (each engine handles
    its own image type), which is what lets fakes drive it in tests.

    `page_offset` is the 0-based index of the first image within the whole
    document, so batched calls still produce globally-correct 1-based page
    numbers.

    An engine that reports `EngineUnavailable` is skipped for the rest of the
    run — no point retrying a missing library on every page."""
    unavailable: set[str] = set()
    results: list[PageResult] = []
    for index, image in enumerate(images):
        best_text, best_conf, best_engine = "", -1.0, None
        attempts: list[Attempt] = []
        for engine in engines:
            if engine.name in unavailable:
                continue
            try:
                res = engine.recognize(image)
            except EngineUnavailable:
                unavailable.add(engine.name)
                attempts.append(Attempt(engine.name, None, "unavailable"))
                continue
            except Exception:  # noqa: BLE001 — one engine failing must not sink the page
                attempts.append(Attempt(engine.name, None, "error"))
                continue
            attempts.append(Attempt(engine.name, res.confidence, "ok"))
            if res.confidence > best_conf:
                best_text, best_conf, best_engine = res.text, res.confidence, engine.name
            if res.confidence >= threshold:
                break  # good enough — don't spend later engines on this page
        page = Page(
            number=page_offset + index + 1,
            text=best_text,
            ocr_engine=best_engine,
            ocr_confidence=best_conf if best_conf >= 0.0 else None,
        )
        results.append(PageResult(page=page, attempts=attempts))
    return results


def pdf_page_count(data: bytes) -> int:
    """Cheap page count — parses the PDF but renders nothing. Used for the
    oversized guardrail and to drive batching."""
    pdf = pdfium.PdfDocument(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def _rasterize_range(data: bytes, start: int, stop: int) -> list[Any]:
    """Render only pages [start, stop) so a batch holds a bounded number of
    page images. Re-opening per batch keeps the path stateless (good for
    resume) and never holds the whole document in memory."""
    pdf = pdfium.PdfDocument(data)
    images: list[Any] = []
    try:
        for i in range(start, stop):
            page = pdf[i]
            scale = min(300 / 72, _TARGET_WIDTH_PX / page.get_size()[0])
            images.append(page.render(scale=scale, grayscale=True).to_pil())
    finally:
        pdf.close()
    return images


def page_result_to_dict(pr: PageResult) -> dict[str, Any]:
    return {
        "page": {
            "number": pr.page.number,
            "text": pr.page.text,
            "ocr_engine": pr.page.ocr_engine,
            "ocr_confidence": pr.page.ocr_confidence,
        },
        "attempts": [
            {"engine": a.engine, "confidence": a.confidence, "status": a.status}
            for a in pr.attempts
        ],
    }


def page_result_from_dict(d: dict[str, Any]) -> PageResult:
    p = d["page"]
    return PageResult(
        page=Page(
            number=p["number"],
            text=p["text"],
            ocr_engine=p["ocr_engine"],
            ocr_confidence=p["ocr_confidence"],
        ),
        attempts=[
            Attempt(a["engine"], a["confidence"], a["status"]) for a in d["attempts"]
        ],
    )


def extract_scanned_pdf(
    data: bytes,
    *,
    engine_chain: list[str],
    threshold: float,
    batch_size: int,
    checkpoint: Checkpoint | None = None,
) -> list[PageResult]:
    """Batched, optionally-checkpointed OCR over a scanned PDF (design §3.2).

    Memory is bounded to one batch of rasterized images regardless of document
    length. When a `checkpoint` is given, each completed batch is persisted and
    an already-persisted batch is loaded instead of re-OCR'd, making the stage
    resumable after a crash/timeout."""
    engines = build_chain(engine_chain)
    page_count = pdf_page_count(data)
    results: list[PageResult] = []
    for start in range(0, page_count, batch_size):
        stop = min(start + batch_size, page_count)
        if checkpoint is not None and checkpoint.has(start):
            results.extend(checkpoint.load(start))
            continue
        images = _rasterize_range(data, start, stop)
        batch = walk_chain(images, engines, threshold, page_offset=start)
        images.clear()  # free this batch's page images before the next batch
        if checkpoint is not None:
            checkpoint.save(start, batch)
        results.extend(batch)
    return results
