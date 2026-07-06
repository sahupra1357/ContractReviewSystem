"""PII hold resolution + master table management (§3.3).

The fail-closed loop: a held document proceeds ONLY after a human either
registers the flagged entity in the master table (re-mask picks it up) or
dismisses the flag with a rationale (suppressed on re-run). Both paths are
audited. The React admin screen (Phase 6) drives these same endpoints.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.api.ingest import get_actor_id
from backend.audit import ActorType, record_event
from backend.db import get_db
from backend.models import Document
from backend.pii.models import HoldStatus, KnownEntity, PiiHold

router = APIRouter(prefix="/pii", tags=["pii"])


class HoldOut(BaseModel):
    id: int
    document_id: str
    flag_type: str
    span_text: str
    detector: str
    score: float | None
    status: str
    created_at: datetime


class ResolveRequest(BaseModel):
    action: str  # "add_to_master" | "dismiss"
    entity_type: str | None = None  # required for add_to_master
    rationale: str | None = None    # required for dismiss


class MasterEntryRequest(BaseModel):
    value: str
    entity_type: str


@router.get("/holds", response_model=list[HoldOut])
def list_holds(
    session: Annotated[Session, Depends(get_db)],
    _actor: Annotated[str, Depends(get_actor_id)],
    status: str = "open",
) -> list[PiiHold]:
    return list(
        session.execute(
            select(PiiHold).where(PiiHold.status == status).order_by(PiiHold.id)
        ).scalars()
    )


@router.post("/holds/{hold_id}/resolve", response_model=HoldOut)
def resolve_hold(
    hold_id: int,
    body: ResolveRequest,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> PiiHold:
    hold = session.get(PiiHold, hold_id)
    if hold is None:
        raise HTTPException(status_code=404, detail="hold not found")
    if hold.status != HoldStatus.open:
        raise HTTPException(status_code=409, detail="hold already resolved")

    if body.action == "add_to_master":
        if not body.entity_type:
            raise HTTPException(status_code=422, detail="entity_type required")
        value = hold.span_text.strip()
        exists = session.execute(
            select(KnownEntity).where(KnownEntity.value == value)
        ).scalar_one_or_none()
        if exists is None:
            entity = KnownEntity(
                value=value, entity_type=body.entity_type, created_by=actor_id
            )
            session.add(entity)
            session.flush()
            record_event(
                session, actor_type=ActorType.human, actor_id=actor_id,
                action="pii_master.added", object_type="pii_known_entity",
                object_id=entity.id,
                detail={"entity_type": body.entity_type, "via_hold": hold.id},
            )
        hold.status = HoldStatus.added_to_master
    elif body.action == "dismiss":
        if not body.rationale or not body.rationale.strip():
            raise HTTPException(status_code=422, detail="rationale required to dismiss")
        hold.status = HoldStatus.dismissed
        hold.rationale = body.rationale
    else:
        raise HTTPException(status_code=422, detail="action must be add_to_master or dismiss")

    hold.resolved_by = actor_id
    hold.resolved_at = datetime.now(UTC)
    record_event(
        session, actor_type=ActorType.human, actor_id=actor_id,
        action=f"pii_hold.{hold.status}", object_type="pii_hold",
        object_id=str(hold.id),
        detail={"document_id": hold.document_id, "flag_type": hold.flag_type},
        rationale=body.rationale,
    )

    open_left = session.execute(
        select(PiiHold).where(
            PiiHold.document_id == hold.document_id,
            PiiHold.status == HoldStatus.open,
        )
    ).first()
    if open_left is None:
        # last hold resolved → re-run the PII gate for this document
        jobs.enqueue(session, document_id=hold.document_id, stage="mask")
        document = session.get(Document, hold.document_id)
        record_event(
            session, actor_type=ActorType.system, actor_id="pii-holds-api",
            action="stage.mask_requeued", object_type="document",
            object_id=document.id, detail={"after_hold": hold.id},
        )
    session.commit()
    return hold


@router.get("/master")
def list_master(
    session: Annotated[Session, Depends(get_db)],
    _actor: Annotated[str, Depends(get_actor_id)],
) -> list[dict]:
    return [
        {"id": e.id, "value": e.value, "entity_type": e.entity_type,
         "created_by": e.created_by}
        for e in session.execute(
            select(KnownEntity).order_by(KnownEntity.created_at)
        ).scalars()
    ]


@router.post("/master", status_code=201)
def add_master_entry(
    body: MasterEntryRequest,
    session: Annotated[Session, Depends(get_db)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> dict:
    exists = session.execute(
        select(KnownEntity).where(KnownEntity.value == body.value)
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="entity already registered")
    entity = KnownEntity(
        value=body.value, entity_type=body.entity_type, created_by=actor_id
    )
    session.add(entity)
    session.flush()
    record_event(
        session, actor_type=ActorType.human, actor_id=actor_id,
        action="pii_master.added", object_type="pii_known_entity",
        object_id=entity.id, detail={"entity_type": body.entity_type},
    )
    session.commit()
    return {"id": entity.id, "value": entity.value, "entity_type": entity.entity_type}
