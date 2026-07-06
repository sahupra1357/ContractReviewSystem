"""PII gate stage — deterministic mask, then fail-closed tripwire (§3.3).

Outcome A (no flags): masked artifact → MASKED zone, status `masked`,
index job enqueued, entity map recorded.
Outcome B (any flag):  status `pii_hold`, holds recorded, NOTHING written
to the masked zone — the document is stopped, not guessed at.

Re-runs (after hold resolution) suppress spans a human dismissed with
rationale, and pick up master-table additions automatically.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.audit import ActorType, record_event
from backend.extraction.fast_path import Page
from backend.extraction.segmenter import segment
from backend.models import Document, DocumentStatus
from backend.pii.masker import mask_text
from backend.pii.models import EntityMapRow, HoldStatus, KnownEntity, PiiHold
from backend.pii.tripwire import detect
from backend.storage import MaskedStorage, RawStorage


def run_pii_gate(
    session: Session,
    raw_storage: RawStorage,
    masked_storage: MaskedStorage,
    document: Document,
    *,
    analyzer_url: str | None = None,
) -> None:
    artifact = json.loads(raw_storage.get_raw(f"{document.id}/extracted.json"))

    known = [
        (e.value, e.entity_type)
        for e in session.execute(select(KnownEntity)).scalars()
    ]
    masked_text, masked_entities = mask_text(artifact["full_text"], known)

    dismissed = {
        (h.flag_type, h.span_text.strip())
        for h in session.execute(
            select(PiiHold).where(
                PiiHold.document_id == document.id,
                PiiHold.status == HoldStatus.dismissed,
            )
        ).scalars()
    }
    flags = detect(masked_text, analyzer_url=analyzer_url, suppressed_spans=dismissed)

    if flags:
        document.status = DocumentStatus.pii_hold
        for flag in flags:
            session.add(
                PiiHold(
                    document_id=document.id,
                    flag_type=flag.flag_type,
                    span_text=flag.span_text[:500],
                    start=flag.start,
                    end=flag.end,
                    detector=flag.detector,
                    score=flag.score,
                    status=HoldStatus.open,
                )
            )
        record_event(
            session,
            actor_type=ActorType.system,
            actor_id="worker:mask",
            action="stage.pii_hold",
            object_type="document",
            object_id=document.id,
            detail={
                "flag_count": len(flags),
                "detectors": sorted({f.detector for f in flags}),
            },
        )
        return

    # clean: refresh the entity map (idempotent re-runs) and release downstream
    for row in session.execute(
        select(EntityMapRow).where(EntityMapRow.document_id == document.id)
    ).scalars():
        session.delete(row)
    for me in masked_entities:
        session.add(
            EntityMapRow(
                document_id=document.id,
                placeholder=me.placeholder,
                entity_value=me.value,
                entity_type=me.entity_type,
                layer="registered",
                occurrences=me.occurrences,
            )
        )

    # re-segment the masked text so section offsets match the masked artifact
    _, masked_sections = segment([Page(number=1, text=masked_text)])
    masked_artifact = {
        "document_id": document.id,
        "method": artifact["method"],
        "masked_text": masked_text,
        "sections": [
            {"section_id": s.section_id, "number": s.number, "heading": s.heading,
             "start": s.start, "end": s.end}
            for s in masked_sections
        ],
        "source_sections": artifact["sections"],  # provenance into raw pages
        "masked_entity_count": len(masked_entities),
    }
    masked_storage.put_masked(
        f"{document.id}/masked.json",
        json.dumps(masked_artifact).encode(),
        "application/json",
    )
    document.status = DocumentStatus.masked
    jobs.enqueue(session, document_id=document.id, stage="index")
    record_event(
        session,
        actor_type=ActorType.system,
        actor_id="worker:mask",
        action="stage.masked",
        object_type="document",
        object_id=document.id,
        detail={
            "masked_entities": len(masked_entities),
            "occurrences": sum(m.occurrences for m in masked_entities),
        },
    )
