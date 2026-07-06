"""Extraction stage entry point: classify → extract → segment.

The returned artifact is RAW (pre-PII-gate). The worker stores it in the
raw zone only; the masking stage (Phase 3) is the sole consumer.
"""

from dataclasses import asdict
from typing import Any

from backend.extraction import fast_path
from backend.extraction.classifier import DocKind, classify
from backend.extraction.segmenter import segment


def extract_document(data: bytes, filename: str) -> dict[str, Any]:
    kind = classify(data, filename)
    if kind == DocKind.born_digital_pdf:
        pages = fast_path.extract_pdf(data)
    elif kind == DocKind.docx:
        pages = fast_path.extract_docx(data)
    elif kind == DocKind.plain_text:
        pages = fast_path.extract_plain(data)
    else:  # scanned → OCR (imported lazily: needs the tesseract binary)
        from backend.extraction.ocr_path import extract_scanned_pdf

        pages = extract_scanned_pdf(data)

    full_text, sections = segment(pages)
    return {
        "method": kind.value,
        "page_count": len(pages),
        "pages": [asdict(p) for p in pages],
        "full_text": full_text,
        "sections": [asdict(s) for s in sections],
    }
