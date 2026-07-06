"""OCR path for scanned/image-only PDFs (design doc §3.2).

Engine: Tesseract (named in the architecture's OCR layer alongside
PaddleOCR/MinerU/Docling). Chosen for the POC because it is CPU-light and
self-hosted; PaddleOCR/Docling are the documented accuracy upgrade for
production scale. Pages are rasterized with pypdfium2 (no system poppler).

Requires the `tesseract` binary (worker image installs it; locally:
`brew install tesseract`).
"""

import pypdfium2 as pdfium
import pytesseract

from backend.extraction.fast_path import Page

_TARGET_WIDTH_PX = 2400  # enough for OCR; caps memory on oversized pages


def extract_scanned_pdf(data: bytes) -> list[Page]:
    pdf = pdfium.PdfDocument(data)
    pages: list[Page] = []
    try:
        for i, page in enumerate(pdf):
            # 300 dpi, but never beyond the target pixel width (scan PDFs
            # often carry pages already sized at raster resolution).
            scale = min(300 / 72, _TARGET_WIDTH_PX / page.get_size()[0])
            bitmap = page.render(scale=scale, grayscale=True)
            image = bitmap.to_pil()
            text = pytesseract.image_to_string(image)
            pages.append(Page(number=i + 1, text=text))
    finally:
        pdf.close()
    return pages
