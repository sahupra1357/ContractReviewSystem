from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.audit import ActorType, AuditEvent, record_event
from backend.db import Base


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_record_event_persists_all_fields():
    session = _session()
    record_event(
        session,
        actor_type=ActorType.human,
        actor_id="reviewer-1",
        action="decision.approved",
        object_type="contract",
        object_id="doc-42",
        detail={"queue_position": 3},
        rationale="Standard terms, no deviations",
    )
    session.commit()

    event = session.execute(select(AuditEvent)).scalar_one()
    assert event.actor_type == ActorType.human
    assert event.actor_id == "reviewer-1"
    assert event.action == "decision.approved"
    assert event.object_type == "contract"
    assert event.object_id == "doc-42"
    assert event.detail == {"queue_position": 3}
    assert event.rationale == "Standard terms, no deviations"
    assert event.created_at is not None


def test_record_event_is_part_of_caller_transaction():
    session = _session()
    record_event(
        session,
        actor_type=ActorType.system,
        actor_id="pipeline",
        action="stage.extracted",
        object_type="contract",
        object_id="doc-1",
    )
    session.rollback()

    assert session.execute(select(AuditEvent)).first() is None
