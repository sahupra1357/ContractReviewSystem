
from backend.auth import get_actor
from backend.main import app
from tests.conftest import make_client


def teardown_function():
    app.dependency_overrides.clear()


def test_upload_requires_auth(session, storage):
    client = make_client(session, storage)
    del app.dependency_overrides[get_actor]  # no identity → 401
    response = client.post(
        "/ingest/upload", files=[("files", ("a.pdf", b"data", "application/pdf"))]
    )
    assert response.status_code == 401


def test_multi_file_upload_with_planted_duplicate(session, storage):
    client = make_client(session, storage)
    response = client.post(
        "/ingest/upload",
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
    client = make_client(session, storage)
    response = client.post(
        "/ingest/upload",
        files=[("files", ("empty.pdf", b"", "application/pdf"))],
    )
    assert response.status_code == 422


def test_upload_attributed_to_jwt_identity(session, storage):
    from sqlalchemy import select

    from backend.models import Document

    client = make_client(session, storage, username="reviewer-7")
    client.post(
        "/ingest/upload",
        files=[("files", ("a.pdf", b"data", "application/pdf"))],
    )
    doc = session.execute(select(Document)).scalar_one()
    assert doc.uploaded_by == "reviewer-7"
