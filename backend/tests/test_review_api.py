"""Review workflow + RBAC (design §3.6, §4) — Gate G6 criteria as tests:
non-reviewer → 403 on decisions; decision without rationale → 422; the
decision endpoint is the only path to approved/rejected; everything audited.
"""

import json

from sqlalchemy import select

from backend.analysis.reference_templates import LEASE_V1
from backend.api.review import Decision
from backend.audit import AuditEvent
from backend.auth import get_actor
from backend.main import app
from backend.models import Document, DocumentStatus, Job
from tests.conftest import make_client


def teardown_function():
    app.dependency_overrides.clear()


def _analyzed_document(session, storage, masked_storage) -> str:
    from backend.analysis.models import Analysis
    from backend.ingestion.core import ingest_document

    result = ingest_document(
        session, storage, source="upload", filename="lease.txt",
        data=b"1. PARTIES\n[ORG-1] and [PERSON-1] agree.\n", actor_id="reviewer-1",
    )
    doc = session.get(Document, result.document_id)
    doc.status = DocumentStatus.analyzed
    masked_storage.put_masked(
        f"{doc.id}/masked.json",
        json.dumps({"masked_text": "1. PARTIES\n[ORG-1] and [PERSON-1] agree.\n",
                    "sections": []}).encode(),
        "application/json",
    )
    session.add(Analysis(
        document_id=doc.id, family="lease-v1", family_score=1.0,
        findings=[{"citation": "c1", "severity": "high", "title": "t",
                   "description": "d"}],
        key_terms={}, suggested_decision="changes_requested", rationale="r",
        dropped_uncited=0, model_strong="m", model_fast="m",
        prompt_version="v1", latency_ms=100,
    ))
    session.commit()
    return doc.id


def test_contract_detail_serves_the_reference_template(session, storage, masked_storage):
    """The reviewer must be able to see WHAT the contract was compared
    against, not just the verdict — every standard clause, in template order,
    with its status."""
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage)

    body = client.get(f"/review/contracts/{doc_id}").json()
    template = body["reference_template"]

    assert template["family"] == "lease-v1"
    assert template["title"] == "RESIDENTIAL LEASE AGREEMENT"
    assert template["thresholds"] == {"standard": 0.85, "deviation": 0.70}
    headings = [c["heading"] for c in template["clauses"]]
    assert headings == [h for h, _ in LEASE_V1["sections"]]
    # the fixture's masked artifact has no sections, so nothing matched
    assert {c["status"] for c in template["clauses"]} == {"missing"}
    assert all(c["template_text"] for c in template["clauses"])


def test_contract_detail_has_no_template_without_an_analysis(
    session, storage, masked_storage,
):
    """Family-undetermined documents go to full manual review — inventing a
    baseline for them would misrepresent what the pipeline actually did."""
    from backend.ingestion.core import ingest_document

    result = ingest_document(
        session, storage, source="upload", filename="scan.txt",
        data=b"illegible\n", actor_id="reviewer-1",
    )
    session.commit()
    client = make_client(session, masked_storage)

    body = client.get(f"/review/contracts/{result.document_id}").json()
    assert body["reference_template"] is None


def test_queue_lists_analyzed_documents(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage)
    queue = client.get("/review/queue").json()
    assert [q["document_id"] for q in queue] == [doc_id]
    assert queue[0]["suggested_decision"] == "changes_requested"
    assert queue[0]["high_severity"] == 1


def test_decision_requires_reviewer_role(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage, role="admin", username="admin-1")
    response = client.post(f"/review/contracts/{doc_id}/decision",
                           json={"action": "approve", "rationale": "fine"})
    assert response.status_code == 403
    assert session.get(Document, doc_id).status == "analyzed"  # unchanged


def test_decision_requires_authentication(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage)
    del app.dependency_overrides[get_actor]
    response = client.post(f"/review/contracts/{doc_id}/decision",
                           json={"action": "approve", "rationale": "fine"})
    assert response.status_code == 401


def test_decision_requires_rationale(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage)
    for bad in ({"action": "approve", "rationale": "   "}, {"action": "approve"}):
        response = client.post(f"/review/contracts/{doc_id}/decision", json=bad)
        assert response.status_code == 422
    assert session.get(Document, doc_id).status == "analyzed"


def test_approve_flow_records_decision_and_audit(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage, username="reviewer-1")

    assert client.post(f"/review/contracts/{doc_id}/claim").status_code == 200
    assert session.get(Document, doc_id).status == "in_review"

    response = client.post(
        f"/review/contracts/{doc_id}/decision",
        json={"action": "approve", "rationale": "Standard terms; deviation acceptable."},
    )
    assert response.status_code == 200
    assert session.get(Document, doc_id).status == "approved"

    decision = session.execute(select(Decision)).scalar_one()
    assert decision.reviewer_username == "reviewer-1"
    assert decision.action == "approve"

    events = [e for e in session.execute(select(AuditEvent)).scalars()
              if e.action == "decision.approved"]
    assert len(events) == 1
    assert events[0].actor_type == "human"
    assert events[0].rationale == "Standard terms; deviation acceptable."

    # audit endpoint shows the full document history including the decision
    audit = client.get(f"/review/contracts/{doc_id}/audit").json()
    assert any(e["action"] == "decision.approved" for e in audit)


def test_request_changes_reenqueues_analysis(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage)
    response = client.post(
        f"/review/contracts/{doc_id}/decision",
        json={"action": "request_changes", "rationale": "Renegotiate liability."},
    )
    assert response.status_code == 200
    assert session.get(Document, doc_id).status == "changes_requested"
    job = session.execute(
        select(Job).where(Job.stage == "analyze", Job.state == "pending")
    ).scalar_one()
    assert job.document_id == doc_id


def test_decision_rejected_for_non_reviewable_status(session, storage, masked_storage):
    doc_id = _analyzed_document(session, storage, masked_storage)
    doc = session.get(Document, doc_id)
    doc.status = DocumentStatus.masked
    session.commit()
    client = make_client(session, masked_storage)
    response = client.post(f"/review/contracts/{doc_id}/decision",
                           json={"action": "approve", "rationale": "x"})
    assert response.status_code == 409


def test_no_pipeline_path_to_approval():
    """Invariant #2 structurally: no pipeline module ASSIGNS the
    approved/rejected states — only the review API does. worker.py may read
    them, exclusively inside its never-touch terminal guard."""
    import pathlib
    import re

    src = pathlib.Path(__file__).parents[1] / "src" / "backend"
    offenders = []
    for path in src.rglob("*.py"):
        rel = path.relative_to(src).as_posix()
        if rel in ("api/review.py", "models.py"):  # definition + decision path
            continue
        text = path.read_text()
        mentions = text.count("DocumentStatus.approved") + text.count(
            "DocumentStatus.rejected")
        if mentions == 0:
            continue
        guard = re.search(
            r"_TERMINAL_STATUSES = \{DocumentStatus\.approved, "
            r"DocumentStatus\.rejected\}", text)
        if rel == "worker.py" and guard and mentions == 2:
            continue  # both mentions are the guard-set literal
        offenders.append(rel)
    assert offenders == []


def test_metrics_shape(session, storage, masked_storage):
    _analyzed_document(session, storage, masked_storage)
    client = make_client(session, masked_storage)
    metrics = client.get("/review/metrics").json()
    assert metrics["documents_by_status"] == {"analyzed": 1}
    assert metrics["total_documents"] == 1
    assert metrics["open_pii_holds"] == 0
