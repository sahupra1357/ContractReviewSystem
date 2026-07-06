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
| LLM | Multi-provider adapter (2026-07-06): Claude API **default** (`CRS_LLM_PROVIDER=anthropic`), Bedrock for production, plus OpenAI-compatible support for GPT, Nemotron, Mistral, MiniMax, Kimi, Qwen. Tiered routing: `llm_model_strong` + `llm_model_fast`. Endpoint/keys from config only |
| UI | React SPA |
| Graph | Postgres graph-lite; Neptune only if ≥3-hop need is proven |
| Golden set | Synthetic contracts (OQ-2 resolved 2026-07-05): 20–30 generated contracts with planted fake PII + planted issues, labels known by construction; must plant both known-list and novel PII; real-contract validation at pre-prod |
| Contract families | OQ-3 resolved 2026-07-06 (real-estate industry): lease agreement, property purchase agreement, vendor/property-services agreement |
| PII gate | Deterministic-primary, fail-closed (2026-07-05, supersedes layered): PII **master table** (real table in POC + admin screen) is the only masking authority (fuzzy/OCR-tolerant matching); Presidio is a detector-only tripwire — any possible unregistered entity halts the doc in `pii_hold` for human resolution. Unknown PII never flows downstream. G3: recall ≥ 0.98 post-hold-resolution + false-alarm rate reported |

## Current status

**ALL PHASES COMPLETE — G0–G7 PASSED** (`docs/gates/`; G7 lists two
presenter rehearsal items: scale corpus to ~100 docs, two cold-start
dry-runs). POC measured numbers are in `docs/gates/G7_report.md`; demo
script in `docs/demo_script.md`. Auth: JWT via `/auth/login` (seed:
`uv run python -m backend.seed_users`; roles reviewer/admin; Cognito-shaped
seam in `backend/auth.py`). Review API under `/review/*` — the decision
endpoint is the ONLY path to approved/rejected (reviewer role + rationale
mandatory; pipeline can never touch terminal decisions). React SPA served
at :8000 from the backend image. LLM: containers use the direct API with
the read-only `ant` profile mount; host-side runs may set
`CRS_LLM_BASE_URL=http://127.0.0.1:8787` (loopback proxy). Do NOT set
empty `ANTHROPIC_*` env vars — empty-but-set shadows the profile. Pipeline: upload → dedup/registry →
extract → PII gate (fail-closed) → index (BGE-M3, hybrid retrieval,
graph-lite) → **analyze** (template diff on masked text, STRONG-model brief
over deviations only w/ mandatory citations + groundedness drop, FAST-model
key terms, injection heuristics) → status `analyzed`. LLM adapter is
multi-provider (`CRS_LLM_PROVIDER`, default anthropic; bedrock; openai-compat
for nvidia/mistral/minimax/kimi/qwen). Canonical contract templates:
`backend.analysis.reference_templates` (golden generator imports from it).
Evals: `extraction_eval`, `pii_eval`, `index_golden`, `retrieval_eval`,
`analysis_eval` (needs LLM creds; 22 analyze jobs queued). ML deps: `uv sync
--extra ml`. Next: finish G5 live eval, then Phase 6 (review app: JWT, queue,
decision API, React UI). `main.py`/`ppt_extract.py` at repo root are scratch.

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
