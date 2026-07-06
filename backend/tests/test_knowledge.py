import json

from sqlalchemy import select

import backend.worker as worker
from backend.knowledge.chunker import chunk_masked_artifact
from backend.knowledge.embedder import HashEmbedder
from backend.knowledge.models import Chunk, EmbeddingCache, GraphEntity, GraphRelationship
from backend.knowledge.retrieval import _rrf
from backend.models import Document, Job
from backend.pii.models import KnownEntity


def _artifact(sections_text: list[tuple[str, str]]) -> dict:
    """Build a masked artifact from (heading, body) pairs."""
    text = ""
    sections = []
    for i, (heading, body) in enumerate(sections_text, start=1):
        start = len(text)
        text += f"{heading}\n{body}\n\n"
        sections.append({
            "section_id": f"sec-{i}", "number": str(i), "heading": heading,
            "start": start, "end": len(text),
        })
    return {"masked_text": text, "sections": sections}


def test_chunker_one_section_one_chunk_with_hash():
    artifact = _artifact([
        ("1. PARTIES", "[ORG-1] and [PERSON-1] agree."),
        ("2. TERM", "The term is 12 months."),
    ])
    chunks = chunk_masked_artifact(artifact)
    assert [c.section_id for c in chunks] == ["sec-1", "sec-2"]
    assert all(c.part == 0 for c in chunks)
    assert chunks[0].sha256 != chunks[1].sha256
    # identical content → identical hash (cache key property)
    again = chunk_masked_artifact(artifact)
    assert [c.sha256 for c in again] == [c.sha256 for c in chunks]


def test_chunker_splits_oversized_sections():
    body = "\n\n".join(f"Paragraph {i} " + "x" * 800 for i in range(10))
    artifact = _artifact([("1. SERVICES", body)])
    chunks = chunk_masked_artifact(artifact)
    assert len(chunks) > 1
    assert {c.section_id for c in chunks} == {"sec-1"}
    assert [c.part for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text) <= 4000 for c in chunks)


def test_rrf_fuses_ranks_across_legs():
    class Row:
        def __init__(self, id):
            self.id = id

    a, b, c = Row("a"), Row("b"), Row("c")
    fused = _rrf([[a, b, c], [b, c, a]])
    order = [row.id for row, _ in fused]
    assert order[0] == "b"  # rank 2 + rank 1 beats a (1+3) and c (3+2)


class RecordingEmbedder(HashEmbedder):
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return super().embed(texts)


def _run_pipeline_to_indexed(session, storage, masked_storage, monkeypatch, body):
    """ingest → extract → mask (no flags) → index with a recording embedder."""
    import backend.pii.service as pii_service
    from backend.ingestion.core import ingest_document
    from backend.worker import process_one

    monkeypatch.setattr(
        pii_service, "detect",
        lambda text, analyzer_url=None, suppressed_spans=None: [],
    )
    embedder = RecordingEmbedder()
    monkeypatch.setattr(worker, "_get_embedder", lambda: embedder)

    session.add(KnownEntity(value="Jordan Rivera", entity_type="PERSON",
                            created_by="test"))
    session.commit()
    result = ingest_document(
        session, storage, source="upload", filename="c.txt", data=body,
        actor_id="reviewer-1", content_type="text/plain",
    )
    session.commit()
    for stage in ("extract", "mask", "index"):
        assert process_one(session, storage, masked_storage, stage=stage)
    return result.document_id, embedder


BODY = (b"1. PARTIES\nJordan Rivera signs for USD 4,200 monthly.\n\n"
        b"2. TERM\nThe term is 24 months starting 2026-03-01.\n")


def test_index_stage_chunks_embeds_and_builds_graph(
    session, storage, masked_storage, monkeypatch
):
    doc_id, embedder = _run_pipeline_to_indexed(
        session, storage, masked_storage, monkeypatch, BODY
    )
    doc = session.get(Document, doc_id)
    assert doc.status == "indexed"

    chunks = session.execute(select(Chunk)).scalars().all()
    assert {c.section_id for c in chunks} == {"sec-1", "sec-2"}
    assert all("Jordan" not in c.text for c in chunks)  # masked text only

    cache = session.execute(select(EmbeddingCache)).scalars().all()
    assert {e.chunk_sha256 for e in cache} == {c.chunk_sha256 for c in chunks}

    parties = [e for e in session.execute(select(GraphEntity)).scalars()
               if e.kind == "party"]
    assert [p.ref for p in parties] == ["[PERSON-1]"]
    assert parties[0].master_entity_id is not None  # linked by id, not value
    terms = {(e.entity_type, e.ref)
             for e in session.execute(select(GraphEntity)).scalars()
             if e.kind == "term"}
    assert ("amount", "USD 4,200") in terms
    assert ("date", "2026-03-01") in terms
    rels = session.execute(select(GraphRelationship)).scalars().all()
    assert {r.rel_type for r in rels} == {"HAS_PARTY", "HAS_TERM"}

    analyze_job = session.execute(
        select(Job).where(Job.stage == "analyze")
    ).scalar_one()
    assert analyze_job.state == "pending"


def test_index_rerun_uses_embedding_cache(session, storage, masked_storage, monkeypatch):
    from backend import jobs as jobqueue
    from backend.worker import process_one

    doc_id, embedder = _run_pipeline_to_indexed(
        session, storage, masked_storage, monkeypatch, BODY
    )
    first_call_count = len(embedder.calls)

    jobqueue.enqueue(session, document_id=doc_id, stage="index")
    session.commit()
    assert process_one(session, storage, masked_storage, stage="index")

    # no new embedding calls (all hashes cached), no duplicate chunks/entities
    assert len(embedder.calls) == first_call_count
    chunks = session.execute(select(Chunk)).scalars().all()
    assert len(chunks) == 2
    parties = [e for e in session.execute(select(GraphEntity)).scalars()
               if e.kind == "party"]
    assert len(parties) == 1


def test_masked_artifact_never_touches_raw_zone_keys(
    session, storage, masked_storage, monkeypatch
):
    doc_id, _ = _run_pipeline_to_indexed(
        session, storage, masked_storage, monkeypatch, BODY
    )
    masked_artifact = json.loads(masked_storage.objects[f"{doc_id}/masked.json"])
    assert "[PERSON-1]" in masked_artifact["masked_text"]
    # raw zone holds original + extracted only; masked zone holds masked only
    assert set(storage.objects) == {f"{doc_id}/c.txt", f"{doc_id}/extracted.json"}
    assert set(masked_storage.objects) == {f"{doc_id}/masked.json"}
