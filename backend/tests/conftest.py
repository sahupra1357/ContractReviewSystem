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
