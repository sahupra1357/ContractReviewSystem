"""Born-digital vs scanned classifier (design doc §3.2).

Born-digital documents skip OCR entirely — the fast path is cheaper AND more
accurate (no OCR errors). Only image-only PDFs go to the OCR path.
"""

import enum
import io

from pypdf import PdfReader

# An image-only PDF yields (near-)zero text from its text layer. Threshold is
# per page: real contracts have hundreds of chars/page.
_MIN_CHARS_PER_PAGE = 25


class DocKind(enum.StrEnum):
    born_digital_pdf = "born-digital-pdf"
    scanned_pdf = "scanned-pdf"
    docx = "docx"
    plain_text = "plain-text"


def classify(data: bytes, filename: str) -> DocKind:
    name = filename.lower()
    if name.endswith(".docx"):
        return DocKind.docx
    if name.endswith((".txt", ".md")):
        return DocKind.plain_text
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        reader = PdfReader(io.BytesIO(data))
        chars = sum(len((page.extract_text() or "").strip()) for page in reader.pages)
        if chars >= _MIN_CHARS_PER_PAGE * max(len(reader.pages), 1):
            return DocKind.born_digital_pdf
        return DocKind.scanned_pdf
    raise ValueError(f"unsupported document type: {filename}")
