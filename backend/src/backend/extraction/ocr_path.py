"""OCR path — confidence-gated multi-engine chain (design doc §3.2).

For each rasterized page we walk the configured engine chain
(Tesseract → PaddleOCR → EasyOCR → Docling by default): a page scoring at or
above the confidence threshold stops the walk; a page below it falls through
to the next engine, and the highest-confidence read wins. Engines whose
library isn't installed are skipped (reported per page). `run_extract`
(service.py) turns a low-confidence page into an `extract_hold`.

Pages are rasterized with pypdfium2 (no system poppler needed). The chain walk
is a pure function (`walk_chain`) so it is unit-tested with fake engines and no
real OCR binary or scanned PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


def walk_chain(
    images: list[Any], engines: list[OcrEngine], threshold: float
) -> list[PageResult]:
    """Run the engine chain over pre-rasterized page images. Pure and
    engine-agnostic: `images` are opaque to this function (each engine handles
    its own image type), which is what lets fakes drive it in tests.

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
            number=index + 1,
            text=best_text,
            ocr_engine=best_engine,
            ocr_confidence=best_conf if best_conf >= 0.0 else None,
        )
        results.append(PageResult(page=page, attempts=attempts))
    return results


def _rasterize(data: bytes) -> list[Any]:
    pdf = pdfium.PdfDocument(data)
    images: list[Any] = []
    try:
        for page in pdf:
            scale = min(300 / 72, _TARGET_WIDTH_PX / page.get_size()[0])
            images.append(page.render(scale=scale, grayscale=True).to_pil())
    finally:
        pdf.close()
    return images


def extract_scanned_pdf(
    data: bytes, *, engine_chain: list[str], threshold: float
) -> list[PageResult]:
    engines = build_chain(engine_chain)
    return walk_chain(_rasterize(data), engines, threshold)
