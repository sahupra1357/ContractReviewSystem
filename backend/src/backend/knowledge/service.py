"""Index stage — chunk, embed (cache-aware), graph-lite (design §3.4).

Reads ONLY the masked zone (invariant #1): this stage never holds a raw
storage handle. Idempotent: re-runs replace the document's chunks and graph;
the embedding cache is keyed by content hash so nothing re-embeds.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import jobs
from backend.audit import ActorType, record_event
from backend.knowledge.chunker import chunk_masked_artifact
from backend.knowledge.embedder import Embedder
from backend.knowledge.graph import rebuild_graph
from backend.knowledge.models import Chunk, EmbeddingCache
from backend.models import Document, DocumentStatus
from backend.storage import MaskedStorage


def run_index(
    session: Session,
    masked_storage: MaskedStorage,
    embedder: Embedder,
    document: Document,
) -> None:
    artifact = json.loads(masked_storage.get_masked(f"{document.id}/masked.json"))
    chunks = chunk_masked_artifact(artifact)

    # idempotent re-run: replace this document's chunks
    for row in session.execute(
        select(Chunk).where(Chunk.document_id == document.id)
    ).scalars():
        session.delete(row)
    session.flush()
    for c in chunks:
        session.add(Chunk(
            document_id=document.id, section_id=c.section_id, part=c.part,
            heading=c.heading, text=c.text, chunk_sha256=c.sha256,
            start=c.start, end=c.end,
        ))

    # embed only cache misses (chunk-hash cache, §3.8)
    hashes = [c.sha256 for c in chunks]
    cached = {
        row.chunk_sha256
        for row in session.execute(
            select(EmbeddingCache).where(
                EmbeddingCache.chunk_sha256.in_(hashes),
                EmbeddingCache.model == embedder.model_name,
            )
        ).scalars()
    }
    to_embed = [c for c in chunks if c.sha256 not in cached]
    seen: set[str] = set()
    to_embed = [c for c in to_embed if not (c.sha256 in seen or seen.add(c.sha256))]
    if to_embed:
        vectors = embedder.embed([c.text for c in to_embed])
        for c, vec in zip(to_embed, vectors, strict=True):
            session.add(EmbeddingCache(
                chunk_sha256=c.sha256, model=embedder.model_name, embedding=vec
            ))

    graph_count = rebuild_graph(session, document, artifact["masked_text"])

    document.status = DocumentStatus.indexed
    jobs.enqueue(session, document_id=document.id, stage="analyze")
    record_event(
        session,
        actor_type=ActorType.system,
        actor_id="worker:index",
        action="stage.indexed",
        object_type="document",
        object_id=document.id,
        detail={
            "chunks": len(chunks),
            "embedded_new": len(to_embed),
            "embedding_cache_hits": len(cached),
            "graph_entities": graph_count,
            "model": embedder.model_name,
        },
    )
