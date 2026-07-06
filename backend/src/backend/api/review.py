"""Review workflow API (design §3.6, §4) — INVARIANT #2 LIVES HERE.

The decision endpoint is the ONLY code path in the system that can move a
document to approved/rejected. It requires an authenticated reviewer and a
non-empty rationale; every decision writes a `decisions` row and a human
audit event. Pipeline code has no route to these states.
"""

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend import jobs
from backend.analysis.models import Analysis
from backend.audit import ActorType, AuditEvent, record_event
from backend.auth import CurrentActor, ReviewerActor
from backend.db import Base, get_db
from backend.knowledge.models import Chunk
from backend.models import Document, DocumentStatus
from backend.pii.models import PiiHold
from backend.storage import MaskedStorage, S3MaskedStorage

router = APIRouter(prefix="/review", tags=["review"])

_REVIEWABLE = {DocumentStatus.analyzed, DocumentStatus.in_review}
_DECISIONS = {
    "approve": DocumentStatus.approved,
    "reject": DocumentStatus.rejected,
    "request_changes": DocumentStatus.changes_requested,
}


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(32))
    reviewer_username: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(30))
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def get_masked_storage() -> MaskedStorage:
    return S3MaskedStorage()


class QueueItem(BaseModel):
    document_id: str
    filename: str
    status: str
    uploaded_by: str
    created_at: datetime
    family: str | None
    suggested_decision: str | None
    finding_count: int | None
    high_severity: int | None


@router.get("/queue", response_model=list[QueueItem])
def review_queue(
    session: Annotated[Session, Depends(get_db)],
    _actor: CurrentActor,
) -> list[QueueItem]:
    rows = session.execute(
        select(Document, Analysis)
        .outerjoin(Analysis, Analysis.document_id == Document.id)
        .where(Document.status.in_([s.value for s in _REVIEWABLE]))
        # triage: urgency metadata first (design §3.6), then oldest first
        .order_by(Document.urgency.is_(None), Document.created_at)
    ).all()
    items = []
    for doc, analysis in rows:
        findings = analysis.findings if analysis else None
        items.append(QueueItem(
            document_id=doc.id, filename=doc.filename, status=doc.status,
            uploaded_by=doc.uploaded_by, created_at=doc.created_at,
            family=analysis.family if analysis else None,
            suggested_decision=analysis.suggested_decision if analysis else None,
            finding_count=len(findings) if findings is not None else None,
            high_severity=sum(1 for f in findings if f.get("severity") == "high")
            if findings is not None else None,
        ))
    return items


@router.get("/contracts/{document_id}")
def contract_detail(
    document_id: str,
    session: Annotated[Session, Depends(get_db)],
    _actor: CurrentActor,
    masked_storage: Annotated[MaskedStorage, Depends(get_masked_storage)],
) -> dict[str, Any]:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    analysis = session.execute(
        select(Analysis).where(Analysis.document_id == document_id)
    ).scalar_one_or_none()
    chunks = list(session.execute(
        select(Chunk).where(Chunk.document_id == document_id)
    ).scalars())

    masked = None
    if doc.status not in (DocumentStatus.ingested, DocumentStatus.extracted,
                          DocumentStatus.pii_hold):
        try:
            masked = json.loads(
                masked_storage.get_masked(f"{document_id}/masked.json")
            )
        except Exception:  # noqa: BLE001 — masked artifact may not exist yet
            masked = None

    decisions = list(session.execute(
        select(Decision).where(Decision.document_id == document_id)
        .order_by(Decision.created_at)
    ).scalars())
    return {
        "document": {
            "id": doc.id, "filename": doc.filename, "status": doc.status,
            "uploaded_by": doc.uploaded_by,
            "created_at": doc.created_at.isoformat(),
        },
        "masked_text": masked["masked_text"] if masked else None,
        "sections": masked["sections"] if masked else [],
        "chunks": [
            {"chunk_id": c.id, "section_id": c.section_id,
             "heading": c.heading, "start": c.start, "end": c.end}
            for c in chunks
        ],
        "analysis": {
            "family": analysis.family,
            "findings": analysis.findings,
            "key_terms": analysis.key_terms,
            "suggested_decision": analysis.suggested_decision,
            "rationale": analysis.rationale,
            "models": {"strong": analysis.model_strong, "fast": analysis.model_fast},
            "latency_ms": analysis.latency_ms,
        } if analysis else None,
        "decisions": [
            {"action": d.action, "rationale": d.rationale,
             "reviewer": d.reviewer_username,
             "created_at": d.created_at.isoformat()}
            for d in decisions
        ],
    }


@router.post("/contracts/{document_id}/claim")
def claim_contract(
    document_id: str,
    session: Annotated[Session, Depends(get_db)],
    actor: ReviewerActor,
) -> dict:
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if doc.status != DocumentStatus.analyzed:
        raise HTTPException(status_code=409,
                            detail=f"cannot claim from status {doc.status!r}")
    doc.status = DocumentStatus.in_review
    record_event(
        session, actor_type=ActorType.human, actor_id=actor.username,
        action="review.claimed", object_type="document", object_id=doc.id,
    )
    session.commit()
    return {"document_id": doc.id, "status": doc.status}


class DecisionRequest(BaseModel):
    action: str          # approve | reject | request_changes
    rationale: str


@router.post("/contracts/{document_id}/decision")
def decide_contract(
    document_id: str,
    body: DecisionRequest,
    session: Annotated[Session, Depends(get_db)],
    actor: ReviewerActor,
) -> dict:
    if body.action not in _DECISIONS:
        raise HTTPException(status_code=422,
                            detail="action must be approve, reject or request_changes")
    if not body.rationale or not body.rationale.strip():
        raise HTTPException(status_code=422, detail="rationale is required")
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if DocumentStatus(doc.status) not in _REVIEWABLE:
        raise HTTPException(status_code=409,
                            detail=f"document is not reviewable (status {doc.status!r})")

    doc.status = _DECISIONS[body.action]
    session.add(Decision(
        document_id=doc.id, reviewer_id=actor.user_id,
        reviewer_username=actor.username, action=body.action,
        rationale=body.rationale,
    ))
    record_event(
        session, actor_type=ActorType.human, actor_id=actor.username,
        action=f"decision.{doc.status}", object_type="document",
        object_id=doc.id, rationale=body.rationale,
    )
    if doc.status == DocumentStatus.changes_requested:
        jobs.enqueue(session, document_id=doc.id, stage="analyze")
    session.commit()
    return {"document_id": doc.id, "status": doc.status}


@router.get("/contracts/{document_id}/audit")
def contract_audit(
    document_id: str,
    session: Annotated[Session, Depends(get_db)],
    _actor: CurrentActor,
) -> list[dict]:
    events = session.execute(
        select(AuditEvent).where(
            AuditEvent.object_type == "document",
            AuditEvent.object_id == document_id,
        ).order_by(AuditEvent.id)
    ).scalars()
    return [
        {"actor_type": e.actor_type, "actor_id": e.actor_id, "action": e.action,
         "detail": e.detail, "rationale": e.rationale,
         "created_at": e.created_at.isoformat()}
        for e in events
    ]


@router.get("/metrics")
def metrics(
    session: Annotated[Session, Depends(get_db)],
    _actor: CurrentActor,
) -> dict:
    by_status = dict(session.execute(
        select(Document.status, func.count()).group_by(Document.status)
    ).all())
    open_holds = session.execute(
        select(func.count()).select_from(PiiHold).where(PiiHold.status == "open")
    ).scalar_one()
    avg_latency = session.execute(select(func.avg(Analysis.latency_ms))).scalar_one()
    decisions = dict(session.execute(
        select(Decision.action, func.count()).group_by(Decision.action)
    ).all())
    return {
        "documents_by_status": by_status,
        "total_documents": sum(by_status.values()),
        "open_pii_holds": open_holds,
        "avg_analysis_latency_ms": float(avg_latency) if avg_latency else None,
        "decisions_by_action": decisions,
    }
