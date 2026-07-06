"""Gate G1 expandability proof: a brand-new connector reaches the ingestion
core through the SourceConnector interface with ZERO changes to core code —
this test only composes existing public APIs."""

from sqlalchemy import select

from backend.ingestion.connectors import SourceConnector, SourceDocument
from backend.ingestion.core import ingest_document
from backend.models import Document


class MockDmsConnector(SourceConnector):
    name = "mock-dms"

    def __init__(self) -> None:
        self._pending = {
            "dms://42": ("lease-42.pdf", b"dms contract 42"),
            "dms://43": ("lease-43.pdf", b"dms contract 43"),
        }
        self.acked: list[str] = []

    def poll(self) -> list[SourceDocument]:
        return [
            SourceDocument(ref=ref, filename=filename)
            for ref, (filename, _) in self._pending.items()
            if ref not in self.acked
        ]

    def fetch(self, ref: str) -> tuple[bytes, str | None]:
        return self._pending[ref][1], "application/pdf"

    def ack(self, ref: str) -> None:
        self.acked.append(ref)


def test_new_connector_needs_no_core_changes(session, storage):
    connector = MockDmsConnector()

    # This loop is what the generic connector runner does — poll, fetch,
    # hand to the core, ack. No core module was modified for this source.
    for item in connector.poll():
        data, content_type = connector.fetch(item.ref)
        result = ingest_document(
            session,
            storage,
            source=connector.name,
            filename=item.filename,
            data=data,
            actor_id=f"connector:{connector.name}",
            content_type=content_type,
            source_ref=item.ref,
        )
        if not result.duplicate:
            connector.ack(item.ref)
    session.commit()

    docs = session.execute(select(Document)).scalars().all()
    assert len(docs) == 2
    assert {d.source for d in docs} == {"mock-dms"}
    assert connector.acked == ["dms://42", "dms://43"]
    assert connector.poll() == []
