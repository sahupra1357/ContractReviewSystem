"""Extract-hold resolution (design doc §3.2, §4).

The fail-closed loop for OCR: a held document proceeds ONLY after an
authenticated reviewer, with a mandatory rationale, either accepts the
best-effort text (→ `extracted`, mask enqueued) or rejects the scan
(→ `failed_extract`). Both paths are audited. This is the OCR twin of the PII
hold-resolution API.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.audit import ActorType, record_event
from backend.auth import ReviewerActor
from backend.db import get_db
from backend.extraction.models import ExtractHold, ExtractHoldStatus
from backend.models import Document, DocumentStatus

router = APIRouter(prefix="/extract", tags=["extract"])


class ExtractHoldOut(BaseModel):
    id: int
    document_id: str
    page_number: int
    confidence: float | None
    attempts: list[dict[str, Any]] | None
    status: str
    created_at: datetime


class ResolveRequest(BaseModel):
    action: str  # "accept_best_effort" | "reject_scan"
    rationale: str | None = None  # mandatory for both


@router.get("/holds", response_model=list[ExtractHoldOut])
def list_holds(
    session: Annotated[Session, Depends(get_db)],
    _actor: ReviewerActor,
    status: str = "open",
) -> list[ExtractHold]:
    return list(
        session.execute(
            select(ExtractHold)
            .where(ExtractHold.status == status)
            .order_by(ExtractHold.id)
        ).scalars()
    )


@router.post("/holds/{hold_id}/resolve", response_model=ExtractHoldOut)
def resolve_hold(
    hold_id: int,
    body: ResolveRequest,
    session: Annotated[Session, Depends(get_db)],
    actor: ReviewerActor,
) -> ExtractHold:
    actor_id = actor.username
    hold = session.get(ExtractHold, hold_id)
    if hold is None:
        raise HTTPException(status_code=404, detail="hold not found")
    if hold.status != ExtractHoldStatus.open:
        raise HTTPException(status_code=409, detail="hold already resolved")
    if not body.rationale or not body.rationale.strip():
        raise HTTPException(status_code=422, detail="rationale required")

    document = session.get(Document, hold.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    if body.action == "accept_best_effort":
        hold.status = ExtractHoldStatus.accepted_best_effort
    elif body.action == "reject_scan":
        hold.status = ExtractHoldStatus.rejected_scan
    else:
        raise HTTPException(
            status_code=422,
            detail="action must be accept_best_effort or reject_scan",
        )
    hold.rationale = body.rationale
    hold.resolved_by = actor_id
    hold.resolved_at = datetime.now(UTC)
    record_event(
        session,
        actor_type=ActorType.human,
        actor_id=actor_id,
        action=f"extract_hold.{hold.status}",
        object_type="extract_hold",
        object_id=str(hold.id),
        detail={"document_id": hold.document_id, "page_number": hold.page_number},
        rationale=body.rationale,
    )

    if body.action == "reject_scan":
        # One rejected page condemns the scan; the document is terminal-failed.
        # Close any sibling open holds so the queue reflects the decision.
        for sibling in session.execute(
            select(ExtractHold).where(
                ExtractHold.document_id == hold.document_id,
                ExtractHold.status == ExtractHoldStatus.open,
            )
        ).scalars():
            sibling.status = ExtractHoldStatus.rejected_scan
            sibling.rationale = body.rationale
            sibling.resolved_by = actor_id
            sibling.resolved_at = datetime.now(UTC)
        document.status = DocumentStatus.failed_extract
        record_event(
            session,
            actor_type=ActorType.system,
            actor_id="extract-holds-api",
            action="stage.failed_extract",
            object_type="document",
            object_id=document.id,
            detail={"reason": "scan rejected at extract_hold", "after_hold": hold.id},
        )
        session.commit()
        return hold

    # accept_best_effort: advance only once every hold on the doc is resolved.
    open_left = session.execute(
        select(ExtractHold).where(
            ExtractHold.document_id == hold.document_id,
            ExtractHold.status == ExtractHoldStatus.open,
        )
    ).first()
    if open_left is None:
        document.status = DocumentStatus.extracted
        jobs.enqueue(session, document_id=document.id, stage="mask")
        record_event(
            session,
            actor_type=ActorType.system,
            actor_id="extract-holds-api",
            action="stage.mask_requeued",
            object_type="document",
            object_id=document.id,
            detail={"after_hold": hold.id, "resolution": "accepted_best_effort"},
        )
    session.commit()
    return hold
