import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db import Base


class FakeRawStorage:
    """In-memory RawStorage for unit tests — no MinIO required."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_raw(self, key: str, data: bytes, content_type: str | None) -> None:
        self.objects[key] = data

    def get_raw(self, key: str) -> bytes:
        return self.objects[key]

    def has_raw(self, key: str) -> bool:
        return key in self.objects


class FakeMaskedStorage:
    """Separate object from raw storage on purpose — tests assert the zones
    never mix (invariant #1)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_masked(self, key: str, data: bytes, content_type: str | None) -> None:
        self.objects[key] = data

    def get_masked(self, key: str) -> bytes:
        return self.objects[key]


@pytest.fixture()
def session():
    # StaticPool + check_same_thread=False: TestClient drives the app from a
    # worker thread; all threads must share the one in-memory database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def storage():
    return FakeRawStorage()


@pytest.fixture()
def masked_storage():
    return FakeMaskedStorage()


def make_client(session, storage=None, *, role="reviewer", username="reviewer-1"):
    """TestClient with DB/storage/auth dependency overrides."""
    from fastapi.testclient import TestClient

    from backend.api.ingest import get_raw_storage
    from backend.api.review import get_masked_storage
    from backend.auth import Actor, get_actor
    from backend.db import get_db
    from backend.main import app

    app.dependency_overrides[get_db] = lambda: session
    if storage is not None:
        app.dependency_overrides[get_raw_storage] = lambda: storage
        if hasattr(storage, "get_masked"):
            app.dependency_overrides[get_masked_storage] = lambda: storage
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id="u-" + username, username=username, role=role
    )
    return TestClient(app)
