"""Hybrid retrieval: pgvector dense + Postgres FTS sparse, fused with
reciprocal-rank fusion, optional BGE cross-encoder rerank (design §3.4).

POC equivalent of Aurora pgvector + OpenSearch hybrid; one store, same
concept, documented upgrade path (design §7).
"""

from dataclasses import dataclass

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from backend.knowledge.embedder import Embedder

RRF_K = 60
CANDIDATES_PER_LEG = 20


@dataclass
class SearchHit:
    chunk_id: str
    document_id: str
    section_id: str
    heading: str
    chunk_text: str
    score: float


def _dense(session: Session, vector: list[float], model: str, limit: int):
    rows = session.execute(
        sql("""
            SELECT c.id, c.document_id, c.section_id, c.heading, c.text
            FROM chunks c
            JOIN embedding_cache e
              ON e.chunk_sha256 = c.chunk_sha256 AND e.model = :model
            ORDER BY e.embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """),
        {"vec": str(vector), "model": model, "limit": limit},
    )
    return list(rows)


def _sparse(session: Session, query: str, limit: int):
    rows = session.execute(
        sql("""
            SELECT c.id, c.document_id, c.section_id, c.heading, c.text
            FROM chunks c
            WHERE c.text_tsv @@ websearch_to_tsquery('english', :q)
            ORDER BY ts_rank(c.text_tsv, websearch_to_tsquery('english', :q)) DESC
            LIMIT :limit
        """),
        {"q": query, "limit": limit},
    )
    return list(rows)


def _rrf(legs: list[list], k: int = RRF_K) -> list[tuple]:
    scores: dict[str, float] = {}
    rows: dict[str, tuple] = {}
    for leg in legs:
        for rank, row in enumerate(leg):
            scores[row.id] = scores.get(row.id, 0.0) + 1.0 / (k + rank + 1)
            rows[row.id] = row
    ordered = sorted(scores, key=scores.get, reverse=True)
    return [(rows[i], scores[i]) for i in ordered]


def search(
    session: Session,
    embedder: Embedder,
    query: str,
    *,
    k: int = 10,
    reranker=None,
) -> list[SearchHit]:
    vector = embedder.embed([query])[0]
    fused = _rrf([
        _dense(session, vector, embedder.model_name, CANDIDATES_PER_LEG),
        _sparse(session, query, CANDIDATES_PER_LEG),
    ])
    hits = [
        SearchHit(chunk_id=row.id, document_id=row.document_id,
                  section_id=row.section_id, heading=row.heading,
                  chunk_text=row.text, score=score)
        for row, score in fused[: max(k, CANDIDATES_PER_LEG if reranker else k)]
    ]
    if reranker is not None and hits:
        scores = reranker.score(query, [h.chunk_text for h in hits])
        for hit, s in zip(hits, scores, strict=True):
            hit.score = float(s)
        hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


class BgeReranker:
    """Cross-encoder rerank (BGE family, per design). Lazy-loaded."""

    model_name = "BAAI/bge-reranker-v2-m3"

    def __init__(self) -> None:
        self._model = None

    def score(self, query: str, texts: list[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model.predict([(query, t) for t in texts]).tolist()
