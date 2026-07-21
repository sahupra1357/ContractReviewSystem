"""OCR engine adapters — one interface behind a confidence-gated chain (§3.2).

Every engine implements `recognize(image) -> OcrResult(text, confidence)` with
confidence normalized to 0–1. **Confidence is mandatory and real** — an adapter
must derive it from the engine's own scores and never fabricate one; when it
cannot (library missing, or no verified score source), it raises
`EngineUnavailable` so the chain skips it rather than inventing a number.

The heavyweight engines (PaddleOCR, EasyOCR, Docling) are optional: they
lazy-import their backing library and raise `EngineUnavailable` if it isn't
installed. Install them with `uv sync --extra ocr`; the default image ships
Tesseract only, which keeps it lean while the whole chain stays testable via
fake engines.

MinerU is deliberately absent from the registry: it delegates OCR to PaddleOCR
internally, so it would add no engine diversity (CLAUDE.md Decision Log,
2026-07-14).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class OcrResult:
    text: str
    confidence: float  # 0–1; the page-level score of THIS engine's read


class EngineUnavailable(RuntimeError):
    """The engine cannot run here (library not installed, or no real
    confidence source wired). The chain skips it and audits the skip — it is
    never treated as a low-confidence read."""


@runtime_checkable
class OcrEngine(Protocol):
    name: str

    def recognize(self, image: Any) -> OcrResult: ...


class TesseractEngine:
    """Tesseract via pytesseract. Confidence = mean per-word `conf` from
    `image_to_data` (0–100 → 0–1), excluding the `-1` non-text entries. The
    prior implementation used `image_to_string`, which discards confidence
    entirely — that missing score is exactly what this chain restores."""

    name = "tesseract"

    def recognize(self, image: Any) -> OcrResult:
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - core dep, present in POC
            raise EngineUnavailable("pytesseract not installed") from exc

        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confs = [
            float(c)
            for word, c in zip(data["text"], data["conf"], strict=False)
            if word.strip() and float(c) >= 0.0
        ]
        # image_to_string preserves reading order/whitespace better than
        # re-joining the word boxes; confidence comes from image_to_data.
        text = pytesseract.image_to_string(image)
        confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return OcrResult(text=text, confidence=confidence)


class EasyOcrEngine:
    """EasyOCR (PyTorch, CRAFT + CRNN). Independent model lineage from
    Tesseract/PaddleOCR. Confidence = mean per-detection score."""

    name = "easyocr"

    def __init__(self) -> None:
        self._reader: Any | None = None

    def _get_reader(self) -> Any:
        if self._reader is None:
            try:
                import easyocr
            except ImportError as exc:
                raise EngineUnavailable("easyocr not installed (uv sync --extra ocr)") from exc
            self._reader = easyocr.Reader(["en"], gpu=False)
        return self._reader

    def recognize(self, image: Any) -> OcrResult:
        try:
            import numpy as np
        except ImportError as exc:
            raise EngineUnavailable("numpy not installed (uv sync --extra ocr)") from exc
        reader = self._get_reader()
        results = reader.readtext(np.array(image), detail=1, paragraph=False)
        if not results:
            return OcrResult(text="", confidence=0.0)
        texts = [text for (_box, text, _conf) in results]
        confs = [float(conf) for (_box, _text, conf) in results]
        return OcrResult(text="\n".join(texts), confidence=sum(confs) / len(confs))


class PaddleOcrEngine:
    """PaddleOCR (classic 2.x `.ocr()` API). Confidence = mean line score.
    The 3.x `.predict()` surface differs; validate against the pinned version
    when the `ocr` extra is enabled at pre-prod."""

    name = "paddleocr"

    def __init__(self) -> None:
        self._ocr: Any | None = None

    def _get_ocr(self) -> Any:
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise EngineUnavailable("paddleocr not installed (uv sync --extra ocr)") from exc
            self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        return self._ocr

    def recognize(self, image: Any) -> OcrResult:
        try:
            import numpy as np
        except ImportError as exc:
            raise EngineUnavailable("numpy not installed (uv sync --extra ocr)") from exc
        result = self._get_ocr().ocr(np.array(image), cls=True)
        lines = result[0] if result else None
        if not lines:
            return OcrResult(text="", confidence=0.0)
        texts = [line[1][0] for line in lines]
        confs = [float(line[1][1]) for line in lines]
        return OcrResult(text="\n".join(texts), confidence=sum(confs) / len(confs))


class DoclingEngine:
    """Docling — last-resort, kept for its layout-aware preprocessing (§3.2).

    Docling wraps external OCR backends and its high-level API exposes no
    verified per-page confidence yet. Emitting a REAL 0–1 page confidence from
    it (never a fabricated one) is a pre-prod task; until that is wired the
    adapter declares itself unavailable so the chain skips it rather than
    inventing a score that could wrongly clear the gate."""

    name = "docling"

    def recognize(self, image: Any) -> OcrResult:
        try:
            import docling  # noqa: F401
        except ImportError as exc:
            raise EngineUnavailable("docling not installed (uv sync --extra ocr)") from exc
        raise EngineUnavailable(
            "docling adapter pending pre-prod confidence wiring — no verified "
            "per-page score source; skipped to keep confidence honest (§3.2)"
        )


_REGISTRY: dict[str, type[OcrEngine]] = {
    TesseractEngine.name: TesseractEngine,
    PaddleOcrEngine.name: PaddleOcrEngine,
    EasyOcrEngine.name: EasyOcrEngine,
    DoclingEngine.name: DoclingEngine,
}


def build_chain(names: list[str]) -> list[OcrEngine]:
    """Instantiate engines for the configured chain. Construction is cheap
    (no model load, no import); libraries load lazily on first `recognize`."""
    chain: list[OcrEngine] = []
    for name in names:
        cls = _REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"unknown OCR engine {name!r}; known: {sorted(_REGISTRY)}"
            )
        chain.append(cls())
    return chain
