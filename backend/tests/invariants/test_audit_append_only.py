"""Invariant #3: the audit trail is append-only, enforced by the DATABASE,
not by application convention. UPDATE and DELETE must fail for every role.

Requires the compose Postgres with migrations applied:
    docker compose up -d postgres
    (cd backend && uv run alembic upgrade head)
    CRS_RUN_INVARIANT_TESTS=1 uv run pytest tests/invariants -m invariant
"""

import os

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.invariant

DATABASE_URL = os.environ.get(
    "CRS_DATABASE_URL", "postgresql+psycopg://crs:crs@localhost:5433/crs"
)

if not os.environ.get("CRS_RUN_INVARIANT_TESTS"):
    pytest.skip(
        "invariant tests need the compose Postgres; set CRS_RUN_INVARIANT_TESTS=1",
        allow_module_level=True,
    )


@pytest.fixture()
def connection():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def _insert_event(conn) -> int:
    return conn.execute(
        text(
            """
            INSERT INTO audit_events
                (actor_type, actor_id, action, object_type, object_id, created_at)
            VALUES
                ('system', 'invariant-test', 'test.event', 'test', 'inv-1', now())
            RETURNING id
            """
        )
    ).scalar_one()


def test_insert_is_allowed(connection):
    event_id = _insert_event(connection)
    assert event_id > 0
    connection.rollback()


def test_update_is_rejected_by_database(connection):
    event_id = _insert_event(connection)
    with pytest.raises(Exception, match="append-only"):
        connection.execute(
            text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
            {"id": event_id},
        )
    connection.rollback()


def test_delete_is_rejected_by_database(connection):
    event_id = _insert_event(connection)
    with pytest.raises(Exception, match="append-only"):
        connection.execute(
            text("DELETE FROM audit_events WHERE id = :id"), {"id": event_id}
        )
    connection.rollback()
