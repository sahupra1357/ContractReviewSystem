# Gate G6 Report — Review Application

**Date:** 2026-07-06
**Phase:** 6 — Application & human review (`docs/02_sdlc_plan.md`; design §3.6, §4)
**Result:** PASS (one dependency noted: the AI brief in the walkthrough was a
staged analysis row because the live-LLM run is still pending per G5 —
auth, workflow, decisions, and audit were exercised for real)

## Gate criteria and evidence (all live against the running stack)

| Criterion | Evidence | Result |
|---|---|---|
| End-to-end walkthrough: ingest → brief → human decision → audit record | gs-0001 appeared in `/review/queue` with AI suggestion + high-severity count; reviewer1 claimed (→ `in_review`) and approved with rationale (→ `approved`); audit shows the full chain ending `human reviewer1 decision.approved <rationale>` | PASS |
| Zero auto-approvals, verifiable from the audit trail alone | `SELECT actor_type, count(*) FROM audit_events WHERE action LIKE 'decision.%'` → **human: 1, system: 0**; plus a structural test asserting no pipeline module references approved/rejected states | PASS |
| RBAC enforced | Live probes on the decision endpoint: no token → **401**; admin role → **403**; blank rationale → **422**. Unit tests cover the same plus non-reviewable status → 409 | PASS |

## What was built

- **Auth (Cognito-shaped seam)**: users table (pbkdf2), `/auth/login` issuing
  JWTs, `get_actor` bearer dependency — the single module production swaps
  for Cognito. Roles: reviewer (decisions), admin (PII master/holds).
  The Phase-1 `X-Actor-Id` placeholder is gone; uploads are attributed to the
  JWT identity. Demo users via `python -m backend.seed_users`.
- **Review API**: triage queue (urgency first, then oldest); contract detail
  (masked text + sections + chunk offsets + brief + decisions); claim;
  **decision endpoint — the only path in the system to approved/rejected**,
  requiring reviewer role + non-empty rationale, writing a `decisions` row
  (migration 0006) + human audit event; `request_changes` re-enqueues
  analysis per the state machine; per-document audit endpoint; metrics.
- **React SPA** (hash-routed, no extra runtime deps): login; multi-file
  upload with per-file duplicate results; live review queue; contract view
  with masked source and brief side-by-side, **clickable citations** that
  scroll+highlight the cited clause (template refs explain missing clauses);
  decision panel with buttons disabled until a rationale is entered; audit
  tab; PII admin (hold queue with add-to-master/dismiss + master table
  registration); live pipeline dashboard.
- **Single-image deployment**: multi-stage Dockerfile (root context) builds
  the UI and serves it from the backend at `:8000` — `docker compose up`
  remains the one-command demo. Verified: `GET /` returns the app, assets 200.

## Tests

55 passed + invariant suite; includes G6-critical: 401/403/422 on decisions,
approve flow with decision row + human audit event + rationale, changes
re-enqueue, 409 on non-reviewable status, JWT attribution of uploads, and the
structural no-pipeline-path-to-approval test.

## Universal checklist (per /security-gate)

- PII isolation: the UI receives masked text only; contract detail reads the
  masked zone exclusively.
- Zero auto-approval: proven live from audit + structurally by test.
- Audit completeness: login, claim, decision (with rationale), plus all prior
  stage events per document via `/review/contracts/{id}/audit`.
- Secrets: JWT secret from config (`CRS_JWT_SECRET`; dev default flagged for
  Phase-7 hardening); demo passwords via `CRS_DEMO_PASSWORD`.
- Docs current: CLAUDE.md updated.

## Notes for Phase 7 (hardening/demo)

1. Staged analysis row used in the walkthrough — replace with the real G5
   live-LLM run before the demo.
2. Dev JWT secret + demo passwords must be overridden for the demo
   environment; compose still uses local dev credentials (POC-acceptable).
3. Frontend served over HTTP locally; production mapping is WAF + internal
   ALB + TLS (design §7).

## Next

Phase 7 — hardening & demo prep (`/demo-prep` skill): run G5 live eval,
seed the 100-contract demo corpus, dry-run the demo script twice, measured
metrics for the deck.
