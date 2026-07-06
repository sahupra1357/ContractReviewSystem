# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project

**AI Contract Review Co-Pilot** — an AI-assisted workflow that helps in-house
legal reviewers navigate, verify, and approve/reject contracts, reducing
review cycle time. Currently building a **POC** for a C-level demo: working
functionality first, designed with scale (10K → millions of documents) in mind.

## Read these before doing anything

1. `docs/03_design_document.md` — **the** authoritative design (architecture,
   data model, invariants, feasibility, open questions).
2. `docs/02_sdlc_plan.md` — phase plan G0–G7 with gates.
3. `docs/01_brainstorm_and_improvements.md` — rationale for deviations from
   the original security review.
4. `project_document/AI_Contract_CoPilot_Security_Review.txt` — original
   security architecture (production north star).

## Non-negotiable invariants

1. **PII gate is absolute.** Downstream stages (embedding, indexing, LLM)
   read only the masked store. Never wire raw text past the gate.
2. **Zero auto-approvals.** No code path may transition a contract to
   approved/rejected except the authenticated human-decision API, which
   requires a rationale.
3. **Everything audited.** Every stage transition, AI suggestion, and human
   action appends to the append-only `audit_events` table. Never grant
   UPDATE/DELETE on it.
4. **No assumptions.** Any dilemma or deviation from the design doc: present
   evidence + a suggestion to the product owner and get confirmation before
   proceeding. Record the outcome in the Decision Log below.

## Decision Log (confirmed with product owner, 2026-07-05)

| Decision | Value |
|---|---|
| Scope | POC: 100 contracts bulk-load, then ~10/day trickle; design for 10K→millions |
| SLA | AI analysis in minutes; human turnaround 1 day; 10 reviewers; goal = reduce review **time** |
| Sources | Connector interface; POC = authenticated multi-file **upload page** (OQ-1 resolved 2026-07-05); DMS + shared filesystem at pre-prod; others are plug-ins later |
| Compliance | SOX-aware (audit-ready structure; certification post-POC) |
| Versioning | Latest version only (upgrade path in design doc §5.4) |
| Platform | Local Docker, AWS-shaped 1:1 (mapping in design doc §7) |
| LLM | Claude API behind a Bedrock-shaped adapter (production = Bedrock) |
| UI | React SPA |
| Graph | Postgres graph-lite; Neptune only if ≥3-hop need is proven |
| Golden set | Synthetic contracts (OQ-2 resolved 2026-07-05): 20–30 generated contracts with planted fake PII + planted issues, labels known by construction; must plant both known-list and novel PII; real-contract validation at pre-prod |
| Contract families | OQ-3 resolved 2026-07-06 (real-estate industry): lease agreement, property purchase agreement, vendor/property-services agreement |
| PII gate | Deterministic-primary, fail-closed (2026-07-05, supersedes layered): PII **master table** (real table in POC + admin screen) is the only masking authority (fuzzy/OCR-tolerant matching); Presidio is a detector-only tripwire — any possible unregistered entity halts the doc in `pii_hold` for human resolution. Unknown PII never flows downstream. G3: recall ≥ 0.98 post-hold-resolution + false-alarm rate reported |

## Current status

**Phase 4 (Knowledge & index) complete** — G0–G4 passed (`docs/gates/`);
G4 recall@10 = 1.000 on 16 labeled queries (metric saturated at POC scale —
re-measure at 10K). Pipeline: upload → dedup/registry → extract → PII gate
(fail-closed) → **index** (clause chunks, BGE-M3 embeddings with chunk-hash
cache, Postgres hybrid retrieval pgvector+FTS+RRF, optional BGE reranker,
graph-lite parties-by-master-id + terms) → analyze job queued (Phase 5).
ML deps are the `ml` extra (`uv sync --extra ml`); compose images include
them (HF cache volume `hfcache`). Evals: `backend.eval.extraction_eval`,
`pii_eval`, `index_golden` then `retrieval_eval` (use
`CRS_DATABASE_URL=...5433...`). Hold resolution + master-table APIs under
`/pii/*`. Next: Phase 5 (AI analysis: template diff, review brief with
citations, Bedrock-shaped Claude adapter). `main.py` and `ppt_extract.py`
at the repo root are scratch files — not application code.

## Stack & layout

- `backend/` — uv project (workspace member): FastAPI (`src/backend/main.py`),
  settings (`config.py`, env prefix `CRS_`), SQLAlchemy (`db.py`), audit
  writer (`audit.py`), Alembic migrations (`alembic/`), tests (`tests/`,
  invariant suite in `tests/invariants/`).
- `frontend/` — React SPA (Vite + TypeScript).
- `docker-compose.yml` — the single environment definition: Postgres+pgvector,
  MinIO (buckets raw/masked/audit auto-created), Presidio analyzer+anonymizer,
  backend (runs migrations on boot).
- `golden_set/` — synthetic labeled eval corpus (README has the label schema).
- `.github/workflows/ci.yml` — lint + tests (with Postgres for invariant
  tests) + frontend build.

## Commands

- `docker compose up -d --build` — boot the full stack (backend on :8000,
  MinIO console :9001, Postgres on host :5433 — 5432 is taken by a local
  Homebrew Postgres).
- Backend (from `backend/`): `uv sync` · `uv run ruff check .` ·
  `uv run pytest -q` (unit) ·
  `CRS_RUN_INVARIANT_TESTS=1 uv run pytest -m invariant` (needs Postgres up,
  migrations applied) · `uv run alembic upgrade head`.
- Frontend (from `frontend/`): `npm install` · `npm run dev` · `npm run build`.

## Project skills (in `.claude/skills/`)

- `/pipeline-stage` — step-by-step guide to implement or modify a pipeline
  stage without breaking the invariants.
- `/add-connector` — add a new document-source connector behind the interface.
- `/security-gate` — run the gate checklist (G0–G7) before declaring a phase done.
- `/demo-prep` — prepare and verify the C-level demo end to end.
- `/unit-tests` — testing standards: pytest/Vitest conventions, synthetic-PII
  fixtures, and the mandatory invariant test suite.
- `/self-evaluate` — self-evaluation loop to run while coding and before
  declaring any task done: spec check, invariant check, run-it-for-real check,
  golden-set eval, honest reporting.

During implementation, `/self-evaluate` is expected after every feature/fix,
and `/unit-tests` governs all test writing.

## Local environment note

`.claude/settings.local.json` sets `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`
(local proxy for the Anthropic API). The application's LLM adapter must read
its endpoint from configuration, never hardcode it.
