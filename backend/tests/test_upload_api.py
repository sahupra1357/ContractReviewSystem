from fastapi.testclient import TestClient

from backend.api.ingest import get_actor_id, get_db, get_raw_storage
from backend.main import app


def _client(session, storage) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_raw_storage] = lambda: storage
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_upload_requires_actor_header(session, storage):
    client = _client(session, storage)
    response = client.post(
        "/ingest/upload", files=[("files", ("a.pdf", b"data", "application/pdf"))]
    )
    assert response.status_code == 401


def test_multi_file_upload_with_planted_duplicate(session, storage):
    client = _client(session, storage)
    response = client.post(
        "/ingest/upload",
        headers={"X-Actor-Id": "reviewer-1"},
        files=[
            ("files", ("a.pdf", b"contract A", "application/pdf")),
            ("files", ("b.pdf", b"contract B", "application/pdf")),
            ("files", ("a-copy.pdf", b"contract A", "application/pdf")),  # duplicate
        ],
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["duplicate"] for r in results] == [False, False, True]
    assert results[2]["document_id"] == results[0]["document_id"]
    assert len(storage.objects) == 2


def test_empty_file_is_rejected(session, storage):
    client = _client(session, storage)
    response = client.post(
        "/ingest/upload",
        headers={"X-Actor-Id": "reviewer-1"},
        files=[("files", ("empty.pdf", b"", "application/pdf"))],
    )
    assert response.status_code == 422


def test_actor_dependency_rejects_blank():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        get_actor_id(None)
