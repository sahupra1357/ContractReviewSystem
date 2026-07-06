# Gate G0 Report — Foundations

**Date:** 2026-07-06
**Phase:** 0 — Foundations (`docs/02_sdlc_plan.md`)
**Result:** PASS (with one scope note, below)

## Gate criteria and evidence

| Criterion | Evidence | Result |
|---|---|---|
| Stack boots with one command | `docker compose up -d --build` → 5/5 services healthy (postgres, minio, presidio-analyzer, presidio-anonymizer, backend); `GET :8000/health` → `{"status":"ok","environment":"compose"}`; buckets raw/masked/audit auto-created by minio-init | PASS |
| CI green | CI workflow created (`.github/workflows/ci.yml`): ruff + migrations + pytest with Postgres service + frontend build. Executed locally, all steps pass; **CI has not run on GitHub — repo has no remote/commits yet** | PASS locally / pending first push |
| Audit schema reviewed | `audit_events` per design doc §5.2: actor(type,id), action, object(type,id), detail JSON, rationale, timestamp; migration `0001` | PASS |
| Append-only proven at DB level | Invariant tests against live compose Postgres: INSERT allowed; UPDATE rejected; DELETE rejected (trigger `audit_events_append_only`) — `CRS_RUN_INVARIANT_TESTS=1 uv run pytest` → 6 passed | PASS |
| Golden-set labeling plan agreed | `golden_set/README.md`: synthetic composition, label schema (PII registered/novel, key terms, known issues), freeze rules, per-gate metrics — per OQ-2 resolution | PASS (product owner to review) |

## Universal checklist (per /security-gate)

- PII isolation: N/A this phase (no pipeline stages exist yet); masked/raw
  bucket separation created in MinIO.
- Zero auto-approval: N/A (no workflow code yet); no decision paths exist.
- Audit completeness: writer (`backend/src/backend/audit.py`) + append-only
  trigger in place and proven.
- Secrets: no credentials hardcoded in application code; compose uses local
  dev defaults (crs/crs, minioadmin) — acceptable for local POC only,
  flagged for demo hardening in Phase 7.
- Tests green: 6 passed (3 unit, 3 invariant). Lint clean.
- Docs current: CLAUDE.md commands/status updated.

## Notes and deviations

1. **Host port 5433 for Postgres** — a local Homebrew Postgres occupies 5432;
   the container publishes 5433 externally (documented in CLAUDE.md).
2. **Presidio smoke test:** analyzer detected PERSON and LOCATION in sample
   text but **missed an account number pattern** out of the box — live
   confirmation of the design decision that deterministic master-table
   masking is primary and Presidio (with custom recognizers, Phase 3) is the
   tripwire.
3. Environment note: `docker compose` requires Docker Desktop running; boot
   from cold Mac start needs `open -a Docker` first.

## Next

Phase 1 — Ingestion & connectors: UploadConnector + landing store + SHA-256
dedup + document registry + job queue (Gate G1).
