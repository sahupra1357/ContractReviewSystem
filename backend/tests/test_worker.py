import json

from sqlalchemy import select

from backend.audit import AuditEvent
from backend.ingestion.core import ingest_document
from backend.models import Document, Job
from backend.worker import process_one


def _ingest_txt(session, storage, body=b"1. PARTIES\nAcme and Rivera agree.\n"):
    result = ingest_document(
        session, storage, source="upload", filename="c.txt",
        data=body, actor_id="reviewer-1", content_type="text/plain",
    )
    session.commit()
    return result


def test_extract_job_produces_artifact_and_status(session, storage, masked_storage):
    result = _ingest_txt(session, storage)

    assert process_one(session, storage, masked_storage, stage="extract") is True
    doc = session.get(Document, result.document_id)
    assert doc.status == "extracted"

    artifact = json.loads(storage.objects[f"{doc.id}/extracted.json"])
    assert artifact["method"] == "plain-text"
    assert artifact["sections"][0]["heading"] == "1. PARTIES"

    job = session.execute(select(Job).where(Job.stage == "extract")).scalar_one()
    assert job.state == "done"
    # extract chains the document into the PII gate
    mask_job = session.execute(select(Job).where(Job.stage == "mask")).scalar_one()
    assert mask_job.state == "pending"
    actions = [e.action for e in session.execute(select(AuditEvent)).scalars()]
    assert actions == ["ingest.landed", "stage.extracted"]
    # queue drained
    assert process_one(session, storage, masked_storage, stage="extract") is False


def test_extract_failure_is_recorded_not_silent(session, storage, masked_storage):
    # a .pdf that is not a PDF → extraction raises → failed_extract
    result = ingest_document(
        session, storage, source="upload", filename="broken.pdf",
        data=b"%PDF-not really", actor_id="reviewer-1", content_type="application/pdf",
    )
    session.commit()

    assert process_one(session, storage, masked_storage, stage="extract") is True
    doc = session.get(Document, result.document_id)
    assert doc.status == "failed_extract"

    job = session.execute(select(Job)).scalar_one()
    assert job.state == "failed"
    assert job.error

    failure_events = [
        e for e in session.execute(select(AuditEvent)).scalars()
        if e.action == "stage.failed_extract"
    ]
    assert len(failure_events) == 1
    assert failure_events[0].detail["error"]


def test_rerun_after_reenqueue_is_idempotent(session, storage, masked_storage):
    from backend import jobs as jobqueue

    result = _ingest_txt(session, storage)
    assert process_one(session, storage, masked_storage, stage="extract") is True

    jobqueue.enqueue(session, document_id=result.document_id, stage="extract")
    session.commit()
    assert process_one(session, storage, masked_storage, stage="extract") is True

    # same artifact key overwritten — no duplicate outputs
    doc = session.get(Document, result.document_id)
    artifact_keys = [k for k in storage.objects if k.endswith("extracted.json")]
    assert artifact_keys == [f"{doc.id}/extracted.json"]
    assert doc.status == "extracted"
