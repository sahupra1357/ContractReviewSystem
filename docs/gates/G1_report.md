# Gate G1 Report — Ingestion & Connectors

**Date:** 2026-07-06
**Phase:** 1 — Ingestion & connectors (`docs/02_sdlc_plan.md`)
**Result:** PASS

## Gate criteria and evidence

| Criterion | Evidence | Result |
|---|---|---|
| 100 docs land exactly once (dedup proven with planted duplicates) | Live bulk upload of 110 files (100 unique + 10 planted duplicates) against the compose stack: response reported 100 new / 10 duplicate; Postgres shows exactly 100 documents for the bulk actor, unique sha256 count equals total documents, one `extract` job per document | PASS |
| Every upload attributed to a user in the audit trail | `audit_events`: one `ingest.landed` per landed document and one `ingest.duplicate_skipped` per duplicate, all with `actor_type=human` and the uploader's actor id; `documents.uploaded_by` populated; upload without `X-Actor-Id` → 401 | PASS |
| Adding a second connector requires no core changes | `tests/test_connector_interface.py`: a MockDmsConnector implements the `SourceConnector` ABC and lands documents through the unchanged public `ingest_document()` — the test composes only existing APIs | PASS |

## Universal checklist (per /security-gate)

- PII isolation: raw bucket written only by the ingestion path; no downstream
  stage exists yet to violate it. Raw keys verified in MinIO (`raw/<doc-id>/<filename>`).
- Zero auto-approval: no decision code paths exist; `models.py` documents that
  approved/rejected transitions are reserved for the human-decision API.
- Audit completeness: every ingest action (landed / duplicate-skipped)
  audited with actor attribution; append-only invariant suite still green.
- Secrets: none added; storage/DB config via `CRS_` env.
- Tests green: 11 passed, 1 skipped locally (invariants pass with
  `CRS_RUN_INVARIANT_TESTS=1`: 14 total). Lint clean.
- Docs current: CLAUDE.md status updated to Phase 1 complete.

## Notes and deviations

1. **Actor attribution is header-based (`X-Actor-Id`)** — an explicitly
   documented placeholder until Phase 6 introduces Cognito-shaped JWT auth;
   `get_actor_id` is the single dependency to swap. Not a gate violation:
   the gate requires attribution, which is present and audited.
2. Bulk load ran as one multi-file request; the ~10/day trickle is the same
   endpoint called repeatedly (no separate mechanism needed).
3. Verification data was synthetic scratch text, cleaned from the stack by
   the Phase 2 golden-set reset (`docker compose down -v` re-seeds cleanly).

## Next

Phase 2 — Extraction: born-digital classifier + fast path, OCR worker
(PaddleOCR/Docling), clause/section structure with provenance (Gate G2).
Prerequisite: golden-set generator (needs OQ-3 — contract families).
