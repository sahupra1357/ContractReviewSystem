"""Large-document extraction — batched, checkpointed OCR + oversized guardrail
(design doc §3.2).

Batching/checkpoint are driven with fake engines and a monkeypatched
rasterizer, so there is no OCR binary or scanned PDF. The oversized path drives
`run_extract`/the resolve API with a monkeypatched `extract_document` to assert
DB/audit effects and the cap-lift on re-extract.
"""

import pytest

from backend.audit import AuditEvent
from backend.extraction import ocr_path, service
from backend.extraction.models import (
    ExtractHold,
    ExtractHoldReason,
    ExtractHoldStatus,
)
from backend.extraction.ocr_engines import OcrResult
from backend.extraction.ocr_path import (
    page_result_from_dict,
    page_result_to_dict,
    walk_chain,
)
from backend.models import Document, DocumentStatus, Job


class FakeEngine:
    def __init__(self, name: str, confidence: float):
        self.name = name
        self._confidence = confidence

    def recognize(self, image):
        return OcrResult(text=f"{self.name}-text", confidence=self._confidence)


class FakeCheckpoint:
    """Serializes through the real to/from-dict helpers, so the round-trip is
    exercised alongside the resume logic."""

    def __init__(self):
        self.blobs: dict[int, list] = {}
        self.saves = 0

    def has(self, start: int) -> bool:
        return start in self.blobs

    def load(self, start: int) -> list:
        return [page_result_from_dict(d) for d in self.blobs[start]]

    def save(self, start: int, batch: list) -> None:
        self.blobs[start] = [page_result_to_dict(pr) for pr in batch]
        self.saves += 1


def test_walk_chain_page_offset_gives_global_page_numbers():
    a = FakeEngine("a", 0.95)
    results = walk_chain([object(), object()], [a], threshold=0.80, page_offset=4)
    assert [r.page.number for r in results] == [5, 6]


def test_page_result_dict_round_trip():
    a = FakeEngine("a", 0.91)
    [pr] = walk_chain([object()], [a], threshold=0.80, page_offset=2)
    back = page_result_from_dict(page_result_to_dict(pr))
    assert back.page.number == 3
    assert back.page.text == "a-text"
    assert back.page.ocr_engine == "a"
    assert back.page.ocr_confidence == 0.91
    assert [(x.engine, x.confidence, x.status) for x in back.attempts] == [
        ("a", 0.91, "ok")
    ]


@pytest.fixture()
def batched(monkeypatch):
    """Patch ocr_path so extract_scanned_pdf runs against fakes: 5 pages, one
    fake engine, and a rasterizer that counts page-range calls."""
    calls: list[tuple[int, int]] = []

    def fake_rasterize(data, start, stop):
        calls.append((start, stop))
        return [object()] * (stop - start)

    monkeypatch.setattr(ocr_path, "pdf_page_count", lambda data: 5)
    monkeypatch.setattr(ocr_path, "build_chain", lambda names: [FakeEngine("a", 0.95)])
    monkeypatch.setattr(ocr_path, "_rasterize_range", fake_rasterize)
    return calls


def test_batched_ocr_bounds_rasterization_and_numbers_pages(batched):
    results = ocr_path.extract_scanned_pdf(
        b"pdf", engine_chain=["a"], threshold=0.80, batch_size=2
    )
    # 5 pages in batches of 2 → three rasterize calls, one per batch.
    assert batched == [(0, 2), (2, 4), (4, 5)]
    assert [r.page.number for r in results] == [1, 2, 3, 4, 5]
    assert all(r.page.ocr_engine == "a" for r in results)


def test_checkpoint_resume_skips_rasterization(batched):
    ckpt = FakeCheckpoint()
    first = ocr_path.extract_scanned_pdf(
        b"pdf", engine_chain=["a"], threshold=0.80, batch_size=2, checkpoint=ckpt
    )
    assert ckpt.saves == 3
    assert batched == [(0, 2), (2, 4), (4, 5)]
    batched.clear()

    # Re-run with the same (now-populated) checkpoint: nothing is rasterized,
    # everything is loaded, and the result is identical (page numbers included).
    second = ocr_path.extract_scanned_pdf(
        b"pdf", engine_chain=["a"], threshold=0.80, batch_size=2, checkpoint=ckpt
    )
    assert batched == []  # no rasterization on resume
    assert ckpt.saves == 3  # no new saves
    assert [r.page.number for r in second] == [r.page.number for r in first]


def test_partial_checkpoint_resumes_from_first_missing_batch(batched):
    ckpt = FakeCheckpoint()
    # Simulate a crash after the first batch: only batch 0 was persisted.
    [pr0, pr1] = ocr_path.walk_chain(
        [object(), object()], [FakeEngine("a", 0.95)], 0.80, page_offset=0
    )
    ckpt.save(0, [pr0, pr1])
    batched.clear()

    ocr_path.extract_scanned_pdf(
        b"pdf", engine_chain=["a"], threshold=0.80, batch_size=2, checkpoint=ckpt
    )
    # Batch 0 loaded from checkpoint; only the remaining batches rasterized.
    assert batched == [(2, 4), (4, 5)]


# ---- oversized guardrail --------------------------------------------------

def test_extract_document_oversized_halts_before_extraction(monkeypatch):
    from backend.extraction.classifier import DocKind

    monkeypatch.setattr(service, "classify", lambda data, name: DocKind.born_digital_pdf)
    monkeypatch.setattr(service.fast_path, "pdf_page_count", lambda data: 1500)

    artifact = service.extract_document(b"pdf", "huge.pdf", max_pages=1000)
    assert artifact["oversized"] is True
    assert artifact["page_count"] == 1500
    assert artifact["max_pages"] == 1000
    assert artifact["pages"] == []  # nothing was extracted


def _doc(session, status=DocumentStatus.ingested) -> Document:
    doc = Document(
        source="upload",
        filename="huge.pdf",
        content_sha256="b" * 64,
        size_bytes=10,
        status=status,
        uploaded_by="tester",
        raw_key="doc/raw.pdf",
    )
    session.add(doc)
    session.flush()
    return doc


def _oversized_artifact():
    return {
        "method": "born-digital-pdf",
        "page_count": 1500,
        "pages": [],
        "full_text": "",
        "sections": [],
        "ocr": None,
        "oversized": True,
        "max_pages": 1000,
    }


def _clean_artifact():
    return {
        "method": "born-digital-pdf",
        "page_count": 3,
        "pages": [],
        "full_text": "text",
        "sections": [{"section_id": "sec-0"}],
        "ocr": None,
        "oversized": False,
    }


def test_run_extract_oversized_records_hold(session, storage, monkeypatch):
    doc = _doc(session)
    storage.put_raw(doc.raw_key, b"pdf", "application/pdf")
    monkeypatch.setattr(service, "extract_document", lambda *a, **k: _oversized_artifact())

    service.run_extract(session, storage, doc)

    assert doc.status == DocumentStatus.extract_hold
    holds = session.query(ExtractHold).filter_by(document_id=doc.id).all()
    assert len(holds) == 1
    assert holds[0].reason == ExtractHoldReason.oversized
    assert holds[0].page_number == 0
    # Nothing flows downstream while held.
    assert session.query(Job).filter_by(document_id=doc.id, stage="mask").count() == 0
    ev = session.query(AuditEvent).filter_by(action="stage.extract_hold").one()
    assert ev.detail["reason"] == "oversized"
    assert ev.detail["page_count"] == 1500


def test_accepted_oversized_lifts_cap_on_reextract(session, storage, monkeypatch):
    doc = _doc(session)
    storage.put_raw(doc.raw_key, b"pdf", "application/pdf")
    session.add(
        ExtractHold(
            document_id=doc.id,
            reason=ExtractHoldReason.oversized,
            page_number=0,
            status=ExtractHoldStatus.accepted_best_effort,
        )
    )
    session.flush()

    captured = {}

    def spy(data, filename, **kwargs):
        captured.update(kwargs)
        return _clean_artifact()

    monkeypatch.setattr(service, "extract_document", spy)
    service.run_extract(session, storage, doc)

    assert captured["max_pages"] == 0  # cap lifted for the accepted re-run
    assert doc.status == DocumentStatus.extracted


def test_oversized_accept_requeues_extract_with_cap_lifted(session, storage):
    from tests.conftest import make_client

    doc = _doc(session, status=DocumentStatus.extract_hold)
    hold = ExtractHold(
        document_id=doc.id,
        reason=ExtractHoldReason.oversized,
        page_number=0,
        status=ExtractHoldStatus.open,
    )
    session.add(hold)
    session.commit()

    client = make_client(session, storage, role="reviewer")
    resp = client.post(
        f"/extract/holds/{hold.id}/resolve",
        json={"action": "accept_best_effort", "rationale": "legit 1500-page lease"},
    )
    assert resp.status_code == 200
    assert resp.json()["reason"] == "oversized"

    session.refresh(doc)
    session.refresh(hold)
    assert hold.status == ExtractHoldStatus.accepted_best_effort
    assert doc.status == DocumentStatus.ingested
    assert session.query(Job).filter_by(document_id=doc.id, stage="extract").count() == 1
    assert session.query(Job).filter_by(document_id=doc.id, stage="mask").count() == 0
    assert (
        session.query(AuditEvent).filter_by(action="stage.extract_requeued").count() == 1
    )


def test_oversized_reject_fails_extract(session, storage):
    from tests.conftest import make_client

    doc = _doc(session, status=DocumentStatus.extract_hold)
    hold = ExtractHold(
        document_id=doc.id,
        reason=ExtractHoldReason.oversized,
        page_number=0,
        status=ExtractHoldStatus.open,
    )
    session.add(hold)
    session.commit()

    client = make_client(session, storage, role="reviewer")
    resp = client.post(
        f"/extract/holds/{hold.id}/resolve",
        json={"action": "reject_scan", "rationale": "garbage upload"},
    )
    assert resp.status_code == 200
    session.refresh(doc)
    assert doc.status == DocumentStatus.failed_extract
    assert session.query(Job).filter_by(document_id=doc.id, stage="extract").count() == 0
