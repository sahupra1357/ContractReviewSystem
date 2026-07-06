"""PII gate stage + fail-closed hold workflow (design §3.3, §4).

The tripwire detector is faked per-test; the gate logic, hold workflow, and
invariants are exercised for real.
"""

import json

from sqlalchemy import select

import backend.pii.service as pii_service
from backend.audit import AuditEvent
from backend.ingestion.core import ingest_document
from backend.main import app
from backend.models import Document, Job
from backend.pii.models import EntityMapRow, HoldStatus, KnownEntity, PiiHold
from backend.pii.tripwire import TripwireFlag
from backend.worker import process_one

BODY = b"1. PARTIES\nAcme Property Holdings LLC and Jordan Rivera agree.\n"


def _land_and_extract(session, storage, masked_storage, body=BODY):
    result = ingest_document(
        session, storage, source="upload", filename="c.txt",
        data=body, actor_id="reviewer-1", content_type="text/plain",
    )
    session.commit()
    assert process_one(session, storage, masked_storage, stage="extract")
    return result.document_id


def _register_known(session):
    session.add_all([
        KnownEntity(value="Acme Property Holdings LLC", entity_type="ORG",
                    created_by="test"),
        KnownEntity(value="Jordan Rivera", entity_type="PERSON", created_by="test"),
    ])
    session.commit()


def _fake_tripwire(monkeypatch, flags):
    monkeypatch.setattr(
        pii_service, "detect", lambda text, analyzer_url=None, suppressed_spans=None: [
            f for f in flags
            if not suppressed_spans
            or (f.flag_type, f.span_text.strip()) not in suppressed_spans
        ],
    )


def test_clean_document_is_masked_and_released(session, storage, masked_storage, monkeypatch):
    _register_known(session)
    _fake_tripwire(monkeypatch, [])
    doc_id = _land_and_extract(session, storage, masked_storage)

    assert process_one(session, storage, masked_storage, stage="mask")
    doc = session.get(Document, doc_id)
    assert doc.status == "masked"

    artifact = json.loads(masked_storage.objects[f"{doc_id}/masked.json"])
    assert "Jordan Rivera" not in artifact["masked_text"]
    assert "Acme Property Holdings" not in artifact["masked_text"]
    assert "[PERSON-1]" in artifact["masked_text"]

    # masked artifact lives ONLY in the masked zone (invariant #1)
    assert f"{doc_id}/masked.json" not in storage.objects

    map_rows = session.execute(select(EntityMapRow)).scalars().all()
    assert {r.entity_value for r in map_rows} == {
        "Acme Property Holdings LLC", "Jordan Rivera",
    }
    index_job = session.execute(select(Job).where(Job.stage == "index")).scalar_one()
    assert index_job.state == "pending"


def test_flagged_document_halts_fail_closed(session, storage, masked_storage, monkeypatch):
    _register_known(session)
    _fake_tripwire(monkeypatch, [
        TripwireFlag(flag_type="PERSON", span_text="Tobias Lindqvist",
                     start=10, end=26, detector="presidio", score=0.9),
    ])
    doc_id = _land_and_extract(
        session, storage, masked_storage,
        body=b"1. PARTIES\nTobias Lindqvist signs for the vendor.\n",
    )

    assert process_one(session, storage, masked_storage, stage="mask")
    doc = session.get(Document, doc_id)
    assert doc.status == "pii_hold"

    # NOTHING reached the masked zone — that is the fail-closed guarantee
    assert masked_storage.objects == {}
    assert session.execute(select(Job).where(Job.stage == "index")).first() is None

    hold = session.execute(select(PiiHold)).scalar_one()
    assert hold.status == HoldStatus.open
    assert hold.span_text == "Tobias Lindqvist"
    actions = [e.action for e in session.execute(select(AuditEvent)).scalars()]
    assert "stage.pii_hold" in actions


def _client(session):
    from tests.conftest import make_client

    return make_client(session, role="admin", username="admin-1")


def teardown_function():
    app.dependency_overrides.clear()


def test_add_to_master_requeues_and_remask_passes(
    session, storage, masked_storage, monkeypatch
):
    _register_known(session)
    flag = TripwireFlag(flag_type="PERSON", span_text="Tobias Lindqvist",
                        start=10, end=26, detector="presidio", score=0.9)
    _fake_tripwire(monkeypatch, [flag])
    doc_id = _land_and_extract(
        session, storage, masked_storage,
        body=b"1. PARTIES\nTobias Lindqvist signs for the vendor.\n",
    )
    assert process_one(session, storage, masked_storage, stage="mask")
    hold_id = session.execute(select(PiiHold)).scalar_one().id

    client = _client(session)
    response = client.post(
        f"/pii/holds/{hold_id}/resolve",
        json={"action": "add_to_master", "entity_type": "PERSON"},
    )
    assert response.status_code == 200

    # the entity is now registered and a mask re-run was queued
    assert session.execute(
        select(KnownEntity).where(KnownEntity.value == "Tobias Lindqvist")
    ).scalar_one()
    # re-run: deterministic layer now masks it; tripwire finds nothing new
    _fake_tripwire(monkeypatch, [])
    assert process_one(session, storage, masked_storage, stage="mask")
    doc = session.get(Document, doc_id)
    assert doc.status == "masked"
    artifact = json.loads(masked_storage.objects[f"{doc_id}/masked.json"])
    assert "Tobias" not in artifact["masked_text"]


def test_dismiss_requires_rationale_and_suppresses_on_rerun(
    session, storage, masked_storage, monkeypatch
):
    _register_known(session)
    flag = TripwireFlag(flag_type="PERSON", span_text="Lake Washington",
                        start=0, end=15, detector="presidio", score=0.6)
    _fake_tripwire(monkeypatch, [flag])
    doc_id = _land_and_extract(
        session, storage, masked_storage,
        body=b"1. PREMISES\nLake Washington view included.\n",
    )
    assert process_one(session, storage, masked_storage, stage="mask")
    hold_id = session.execute(select(PiiHold)).scalar_one().id
    client = _client(session)

    # no rationale → rejected
    response = client.post(
        f"/pii/holds/{hold_id}/resolve",
        json={"action": "dismiss"},
    )
    assert response.status_code == 422

    response = client.post(
        f"/pii/holds/{hold_id}/resolve",
        json={"action": "dismiss", "rationale": "Lake name, not a person"},
    )
    assert response.status_code == 200

    # re-run keeps the same detector output, but the dismissed span is
    # suppressed → document proceeds
    assert process_one(session, storage, masked_storage, stage="mask")
    assert session.get(Document, doc_id).status == "masked"
