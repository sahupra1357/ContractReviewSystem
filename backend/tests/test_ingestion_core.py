from sqlalchemy import select

from backend.audit import AuditEvent
from backend.ingestion.core import ingest_document
from backend.models import Document, Job


def _ingest(session, storage, data=b"contract body", filename="lease.pdf"):
    return ingest_document(
        session,
        storage,
        source="upload",
        filename=filename,
        data=data,
        actor_id="reviewer-1",
        content_type="application/pdf",
    )


def test_new_document_lands_once(session, storage):
    result = _ingest(session, storage)
    session.commit()

    assert not result.duplicate
    doc = session.execute(select(Document)).scalar_one()
    assert doc.status == "ingested"
    assert doc.content_sha256 == result.sha256
    assert doc.uploaded_by == "reviewer-1"
    assert storage.objects[doc.raw_key] == b"contract body"

    job = session.execute(select(Job)).scalar_one()
    assert job.document_id == doc.id
    assert job.stage == "extract"
    assert job.state == "pending"

    events = session.execute(select(AuditEvent)).scalars().all()
    assert [e.action for e in events] == ["ingest.landed"]
    assert events[0].actor_id == "reviewer-1"
    assert events[0].object_id == doc.id


def test_duplicate_is_skipped_and_audited(session, storage):
    first = _ingest(session, storage)
    session.commit()
    second = _ingest(session, storage, filename="lease-copy.pdf")
    session.commit()

    assert second.duplicate
    assert second.document_id == first.document_id
    # exactly one document, one job, one raw object — idempotency
    assert len(session.execute(select(Document)).scalars().all()) == 1
    assert len(session.execute(select(Job)).scalars().all()) == 1
    assert len(storage.objects) == 1

    actions = [e.action for e in session.execute(select(AuditEvent)).scalars()]
    assert actions == ["ingest.landed", "ingest.duplicate_skipped"]


def test_different_content_is_not_a_duplicate(session, storage):
    _ingest(session, storage, data=b"contract A")
    second = _ingest(session, storage, data=b"contract B")
    session.commit()

    assert not second.duplicate
    assert len(session.execute(select(Document)).scalars().all()) == 2
