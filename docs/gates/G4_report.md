# Gate G4 Report — Knowledge & Index

**Date:** 2026-07-06
**Phase:** 4 — Knowledge & index (`docs/02_sdlc_plan.md`; design §3.4)
**Result:** PASS

## Gate criteria and evidence

| Criterion | Threshold | Measured | Result |
|---|---|---|---|
| Hybrid retrieval recall@10 on 16 labeled golden queries | ≥ 0.85 | **1.000** (recall@5 also 1.000; every query hit at rank 0) | PASS |
| Entity extraction spot-check (graph-lite) | pass | Parties linked by master-id (never raw values), amounts/dates/durations extracted; unit-tested + verified on live corpus | PASS |

Eval commands:
`uv run python -m backend.eval.index_golden` (pipeline → 22/22 indexed),
`uv run python -m backend.eval.retrieval_eval` (BGE-M3, hybrid, no rerank).
Query set: 5 planted-deviation queries (must find the specific deviating
document+section) + 11 standard-clause queries (family sets).

## What was built

- Migration 0004: pgvector extension, `chunks` (masked text + generated
  tsvector + GIN), `embedding_cache` keyed by (chunk_sha256, model),
  graph-lite `entities`/`relationships`.
- **Chunker**: clause = chunk (sections from the masked artifact), oversized
  sections split on paragraph bounds; content hash is the cache key.
- **Embedder**: self-hosted **BAAI/bge-m3** (sentence-transformers, lazy
  load, normalized 1024-dim). Deterministic HashEmbedder double for tests/CI.
- **Embedding cache**: re-index of the corpus embeds 0 new chunks (verified
  by unit test asserting no embedder calls on re-run).
- **Graph-lite**: party entities from the PII entity map referencing
  `pii_known_entities` by id only — cross-contract "same party" joins
  without exposing raw values; term entities (USD amounts, ISO dates,
  month durations) from masked text; HAS_PARTY / HAS_TERM relationships.
- **Hybrid retrieval**: pgvector cosine (dense) + Postgres `websearch_to_tsquery`
  (sparse) → reciprocal-rank fusion; optional `BgeReranker`
  (BAAI/bge-reranker-v2-m3) behind the same interface.
- Index worker stage chained mask → index → analyze-job enqueued;
  compose images now carry the ML stack with a shared HF-cache volume.

## Fail-closed behavior observed during the live run (worth showing the C-team)

Both deliberately-poor scans (gs-0018, gs-0021) produced OCR garbage that
Presidio flagged as possible PERSON entities → both documents **halted in
`pii_hold`** during the golden indexing run. The eval resolved them exactly
as a human would (dismiss with rationale → auto re-mask → indexed). This is
the designed behavior on degraded input: uncertainty stops the document; a
human decision — not a heuristic — releases it. Hold burden on this corpus:
2/22 documents, both poor scans.

## Honest caveats

1. **Recall 1.000 saturates the metric on a 22-doc corpus** — retrieval
   discrimination is easy at this scale. The gate is honest for a POC; the
   10K pilot must re-measure (queries and harness are reusable as-is).
2. **Reranker implemented but not exercised**: with the baseline at 1.000
   there is nothing for the cross-encoder to lift on this corpus. The
   security review's "~40% retrieval lift" claim remains **unvalidated on
   our own data** — measure during the 10K phase; do not quote it in the
   deck as ours.
3. In-container BGE inference (worker image) is built but was not load-tested
   in this phase; the golden run used host-side inference against the compose
   stack. Verify container inference in Phase 7 demo prep.

## Universal checklist (per /security-gate)

- PII isolation: the index stage holds NO raw-storage handle (structural);
  chunks/entities/graph built exclusively from masked artifacts; unit test
  asserts raw-zone keys never include masked artifacts.
- Zero auto-approval: untouched; analyze jobs queue pending for Phase 5.
- Audit: `stage.indexed` with chunk/embedding-cache/graph counts per doc.
- Tests green: 42 passed + invariants; lint clean.
- Docs current: CLAUDE.md updated.

## Next

Phase 5 — AI analysis: template/family detection, clause deviation diff,
review-brief generation with mandatory citations (Claude API behind the
Bedrock-shaped adapter), tiered routing, groundedness check (Gate G5).
