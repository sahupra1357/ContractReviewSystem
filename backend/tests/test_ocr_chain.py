"""OCR confidence-gated chain + extract_hold (design doc §3.2).

The chain walk is exercised with fake engines (fixed per-call confidence +
call counters) — no OCR binary, no scanned PDF. The hold path drives
`run_extract` with a monkeypatched `extract_document` so we assert the DB/audit
effects without real rasterization.
"""

import pytest

from backend.audit import AuditEvent
from backend.extraction.models import ExtractHold, ExtractHoldStatus
from backend.extraction.ocr_engines import EngineUnavailable, OcrResult
from backend.extraction.ocr_path import walk_chain
from backend.models import Document, DocumentStatus, Job


class FakeEngine:
    """Returns a fixed confidence every call; counts calls so tests can assert
    whether the chain fell through to it."""

    def __init__(self, name: str, confidence: float | None, *, unavailable=False, error=False):
        self.name = name
        self._confidence = confidence
        self._unavailable = unavailable
        self._error = error
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self._unavailable:
            raise EngineUnavailable(f"{self.name} unavailable")
        if self._error:
            raise ValueError(f"{self.name} boom")
        return OcrResult(text=f"{self.name}-text", confidence=self._confidence)


IMG = object()  # opaque page image; fake engines ignore it


def test_first_engine_passes_no_fallback():
    a = FakeEngine("a", 0.95)
    b = FakeEngine("b", 0.99)
    [result] = walk_chain([IMG], [a, b], threshold=0.80)
    assert result.page.ocr_engine == "a"
    assert result.page.ocr_confidence == 0.95
    assert b.calls == 0  # never fell through — the whole point of the gate


def test_low_page_falls_through_best_wins():
    a = FakeEngine("a", 0.40)
    b = FakeEngine("b", 0.92)
    c = FakeEngine("c", 0.99)
    [result] = walk_chain([IMG], [a, b, c], threshold=0.80)
    assert a.calls == 1 and b.calls == 1
    assert c.calls == 0  # stopped once b cleared the threshold
    assert result.page.ocr_engine == "b"
    assert result.page.text == "b-text"


def test_all_engines_below_threshold_keeps_best():
    a = FakeEngine("a", 0.30)
    b = FakeEngine("b", 0.55)
    c = FakeEngine("c", 0.50)
    [result] = walk_chain([IMG], [a, b, c], threshold=0.80)
    assert a.calls == b.calls == c.calls == 1  # walked the whole chain
    assert result.page.ocr_engine == "b"  # 0.55 is the highest
    assert result.page.ocr_confidence == 0.55
    assert [a.status for a in result.attempts] == ["ok", "ok", "ok"]


def test_unavailable_engine_skipped_and_not_retried():
    a = FakeEngine("a", None, unavailable=True)
    b = FakeEngine("b", 0.90)
    results = walk_chain([IMG, IMG], [a, b], threshold=0.80)
    assert a.calls == 1  # tried once, then skipped for page 2
    assert b.calls == 2
    assert all(r.page.ocr_engine == "b" for r in results)
    assert results[0].attempts[0].status == "unavailable"


def test_errored_engine_recorded_and_chain_continues():
    a = FakeEngine("a", None, error=True)
    b = FakeEngine("b", 0.90)
    [result] = walk_chain([IMG], [a, b], threshold=0.80)
    assert result.attempts[0].status == "error"
    assert result.page.ocr_engine == "b"


def test_page_with_no_engine_result_has_none_confidence():
    a = FakeEngine("a", None, unavailable=True)
    [result] = walk_chain([IMG], [a], threshold=0.80)
    assert result.page.ocr_confidence is None  # infra failure, not low-conf


# ---- run_extract: hold / clean / infra-failure paths ----------------------


def _doc(session, status=DocumentStatus.ingested) -> Document:
    doc = Document(
        source="upload",
        filename="scan.pdf",
        content_sha256="a" * 64,
        size_bytes=10,
        status=status,
        uploaded_by="tester",
        raw_key="doc/raw.pdf",
    )
    session.add(doc)
    session.flush()
    return doc


def _artifact(ocr):
    return {
        "method": "scanned-pdf",
        "page_count": 1,
        "pages": [],
        "full_text": "best effort text",
        "sections": [{"section_id": "sec-0"}],
        "ocr": ocr,
    }


def _low_conf_ocr():
    return {
        "engine_chain": ["tesseract"],
        "threshold": 0.80,
        "pages": [
            {"page": 1, "engine": "tesseract", "confidence": 0.5,
             "attempts": [{"engine": "tesseract", "confidence": 0.5, "status": "ok"}]},
        ],
        "min_confidence": 0.5,
        "low_confidence_pages": [1],
        "failed_pages": [],
        "unavailable_engines": [],
    }


def test_run_extract_low_confidence_holds(session, storage, monkeypatch):
    from backend.extraction import service

    doc = _doc(session)
    storage.put_raw(doc.raw_key, b"pdf", "application/pdf")
    monkeypatch.setattr(service, "extract_document", lambda *a, **k: _artifact(_low_conf_ocr()))

    service.run_extract(session, storage, doc)

    assert doc.status == DocumentStatus.extract_hold
    holds = session.query(ExtractHold).filter_by(document_id=doc.id).all()
    assert len(holds) == 1 and holds[0].page_number == 1 and holds[0].confidence == 0.5
    assert session.query(Job).filter_by(document_id=doc.id, stage="mask").count() == 0
    assert session.query(AuditEvent).filter_by(action="stage.extract_hold").count() == 1
    # the best-effort artifact is still persisted (raw zone) for later accept
    assert f"{doc.id}/extracted.json" in storage.objects


def test_run_extract_hold_is_idempotent(session, storage, monkeypatch):
    from backend.extraction import service

    doc = _doc(session)
    storage.put_raw(doc.raw_key, b"pdf", "application/pdf")
    monkeypatch.setattr(service, "extract_document", lambda *a, **k: _artifact(_low_conf_ocr()))

    service.run_extract(session, storage, doc)
    service.run_extract(session, storage, doc)  # re-run must not duplicate holds

    assert session.query(ExtractHold).filter_by(document_id=doc.id).count() == 1


def test_run_extract_clean_advances_to_mask(session, storage, monkeypatch):
    from backend.extraction import service

    doc = _doc(session)
    storage.put_raw(doc.raw_key, b"pdf", "application/pdf")
    # born-digital: ocr is None, so no confidence gate
    monkeypatch.setattr(service, "extract_document", lambda *a, **k: _artifact(None))

    service.run_extract(session, storage, doc)

    assert doc.status == DocumentStatus.extracted
    assert session.query(Job).filter_by(document_id=doc.id, stage="mask").count() == 1
    assert session.query(AuditEvent).filter_by(action="stage.extracted").count() == 1


def test_run_extract_no_engine_result_raises(session, storage, monkeypatch):
    from backend.extraction import service

    doc = _doc(session)
    storage.put_raw(doc.raw_key, b"pdf", "application/pdf")
    ocr = _low_conf_ocr()
    ocr["failed_pages"] = [2]
    monkeypatch.setattr(service, "extract_document", lambda *a, **k: _artifact(ocr))

    with pytest.raises(RuntimeError, match="no result"):
        service.run_extract(session, storage, doc)


# ---- resolution API --------------------------------------------------------


def _open_hold(session, doc, page=1) -> ExtractHold:
    hold = ExtractHold(
        document_id=doc.id, page_number=page, confidence=0.5,
        attempts=[{"engine": "tesseract", "confidence": 0.5, "status": "ok"}],
        status=ExtractHoldStatus.open,
    )
    session.add(hold)
    session.commit()
    return hold


def test_accept_best_effort_advances_document(session, storage):
    from tests.conftest import make_client

    doc = _doc(session, status=DocumentStatus.extract_hold)
    hold = _open_hold(session, doc)
    client = make_client(session, storage, role="reviewer")

    resp = client.post(f"/extract/holds/{hold.id}/resolve",
                       json={"action": "accept_best_effort", "rationale": "legible enough"})
    assert resp.status_code == 200
    session.refresh(doc)
    assert doc.status == DocumentStatus.extracted
    assert session.query(Job).filter_by(document_id=doc.id, stage="mask").count() == 1


def test_reject_scan_fails_document(session, storage):
    from tests.conftest import make_client

    doc = _doc(session, status=DocumentStatus.extract_hold)
    hold = _open_hold(session, doc)
    client = make_client(session, storage, role="reviewer")

    resp = client.post(f"/extract/holds/{hold.id}/resolve",
                       json={"action": "reject_scan", "rationale": "illegible; rescan"})
    assert resp.status_code == 200
    session.refresh(doc)
    assert doc.status == DocumentStatus.failed_extract
    assert session.query(Job).filter_by(document_id=doc.id, stage="mask").count() == 0


def test_resolve_requires_rationale(session, storage):
    from tests.conftest import make_client

    doc = _doc(session, status=DocumentStatus.extract_hold)
    hold = _open_hold(session, doc)
    client = make_client(session, storage, role="reviewer")

    resp = client.post(f"/extract/holds/{hold.id}/resolve",
                       json={"action": "accept_best_effort", "rationale": "  "})
    assert resp.status_code == 422


def test_resolve_rejects_second_resolution(session, storage):
    from tests.conftest import make_client

    doc = _doc(session, status=DocumentStatus.extract_hold)
    hold = _open_hold(session, doc)
    client = make_client(session, storage, role="reviewer")

    ok = client.post(f"/extract/holds/{hold.id}/resolve",
                     json={"action": "accept_best_effort", "rationale": "ok"})
    assert ok.status_code == 200
    again = client.post(f"/extract/holds/{hold.id}/resolve",
                        json={"action": "reject_scan", "rationale": "changed mind"})
    assert again.status_code == 409
