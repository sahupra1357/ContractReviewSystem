"""Fast path — direct text extraction for born-digital documents (§3.2).

Output preserves page provenance so downstream citations can point back to
the exact page. NOTE: extracted text is RAW (pre-PII-gate) — it must only
ever be written to the raw zone.
"""

import io
from dataclasses import dataclass

from docx import Document as DocxDocument
from pypdf import PdfReader


@dataclass
class Page:
    number: int  # 1-based
    text: str
    # Set only on the OCR path (§3.2); None for born-digital fast-path pages.
    ocr_engine: str | None = None
    ocr_confidence: float | None = None  # 0–1, the winning engine's page score


def pdf_page_count(data: bytes) -> int:
    """Page count without rendering — drives the oversized guardrail (§3.2).
    Uses pypdf (a base dependency) so the guardrail never pulls in the heavy
    OCR extra for born-digital documents."""
    return len(PdfReader(io.BytesIO(data)).pages)


def extract_pdf(data: bytes) -> list[Page]:
    reader = PdfReader(io.BytesIO(data))
    return [
        Page(number=i + 1, text=(page.extract_text() or ""))
        for i, page in enumerate(reader.pages)
    ]


def extract_docx(data: bytes) -> list[Page]:
    doc = DocxDocument(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    return [Page(number=1, text=text)]  # docx has no fixed pagination


def extract_plain(data: bytes) -> list[Page]:
    return [Page(number=1, text=data.decode("utf-8", errors="replace"))]
