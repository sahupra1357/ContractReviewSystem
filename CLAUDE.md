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
| OCR | Confidence-gated multi-engine chain (2026-07-14, supersedes single-engine Tesseract; design doc §3.2): Tesseract → PaddleOCR → EasyOCR → Docling-last-resort (`CRS_OCR_ENGINE_CHAIN`), one adapter interface `ocr(page_image) → (text, confidence)`. MinerU **excluded** (2026-07-14: wraps PaddleOCR, no engine diversity); Docling kept last-resort for layout-aware rescue, RapidOCR backend (wraps external OCR — default EasyOCR — so lineage redundancy accepted). Per-page confidence mandatory, normalized 0–1 (Tesseract must use `image_to_data`, not `image_to_string`). Page below `CRS_OCR_CONFIDENCE_THRESHOLD` (default 0.80) retries the **next engine, that page only**; highest-confidence result wins. All engines below threshold → **`extract_hold`** (fail-closed, mirrors `pii_hold`): reviewer accepts best-effort text w/ rationale (→ `extracted`, mask enqueued) or rejects the scan (→ `failed_extract`); resolution API `/extract/holds`. Every attempt audited. **Implemented 2026-07-14** (`extraction/ocr_engines.py` adapters, `ocr_path.walk_chain`, `run_extract`, `ExtractHold` + migration 0007, `api/extract.py`). Heavy engines are the optional `ocr` extra (`uv sync --extra ocr`); default image = Tesseract only, others lazy-import + skip-with-audit. Tesseract adapter real (confidence via `image_to_data`); PaddleOCR/EasyOCR real adapters (validate at pre-prod when extra installed); Docling registered but reports unavailable until its per-page confidence is wired (never fabricated) |
| Embeddings on Render | Confirmed 2026-08-13: **both** Render blueprints set `CRS_EMBEDDING_PROVIDER=openai` (`text-embedding-3-small` at 1024 dims) and build with `CRS_EXTRAS=openai`. `render.yaml` therefore loses the worker's `hf-cache` disk and drops `pro`→`standard` (peak memory is now OCR, not inference). **Local compose and the in-VPC AWS build keep `bge-m3` — the design default is unchanged.** Consequence: G4/G5 numbers were measured on BGE-M3 and do not describe either Render deployment; vectors are partitioned by `model_name`, so a provider switch requires a re-index but can never silently mix |
| Free-tier demo hosting | Confirmed 2026-08-13 (`docs/deploy_vercel_render.md`, `render.free.yaml`): Vercel (SPA) + Render free web service (API **and** pipeline) + Cloudflare R2 + Modal. Render's free tier has no worker tier, no private services and no disks, so four of `render.yaml`'s six services are relocated — **every swap is a config flag whose default is the original component; nothing was removed**. `CRS_INLINE_WORKER=1` runs the pipeline loop in-process under a restart supervisor (default `0` = standalone worker); `CRS_S3_*` + `CRS_S3_REGION=auto` point at R2 (default MinIO); `CRS_PRESIDIO_ANALYZER_URL` points at Modal (`deploy/modal_presidio.py` hosts the official image unmodified); the Presidio **anonymizer was deleted outright** (2026-08-14) — nothing ever called it, since the master table does all masking. Embeddings: `CRS_EMBEDDING_PROVIDER=openai` (`text-embedding-3-small` requested at 1024 dims = `EMBEDDING_DIM`, so **no migration**; `model_name` is provider-qualified so BGE-M3 and OpenAI vectors can never mix) — default stays `bge-m3`. Image slims 8.66GB → **697MB** via `ARG CRS_EXTRAS=openai` (skips torch; the reranker is eval-only so serving is unaffected). **Cost: G4/G5 metrics were measured on BGE-M3 and do not hold on this deployment** — re-run evals or present them as reference-stack numbers. Free Postgres **expires 30 days after creation**; free web service sleeps after 15 idle min. Verified 2026-08-13 on the slim image: extract → mask → `pii_hold` with `detectors: ["presidio"]`, fail-closed gate and audit trail intact. The full-cloud rollout sets none of these flags |
| Large-document extraction | Batched, checkpointed OCR (2026-07-15, design doc §3.2/§5.2/§8-F11): **Implemented 2026-07-15** (`ocr_path.extract_scanned_pdf` batches + `Checkpoint`/`RawZoneCheckpoint`, `walk_chain(page_offset=…)`, `service.extract_document` oversized guardrail + `_record_oversized_hold`, `ExtractHoldReason` + migration 0008, `api/extract.py` oversized-accept re-extract; `CRS_OCR_BATCH_SIZE`/`CRS_EXTRACT_MAX_PAGES`; verified on a real 6-page scan with Tesseract — bounded per-batch rasterization + partial-crash resume). Real contracts can run to 100s of pages; the current OCR path rasterizes the whole PDF into memory at once (`ocr_path._rasterize` → `walk_chain`), so peak memory grows with page count (~2 GB for a 300-page scan) and a crash re-OCRs the whole doc. Fix: process pages in bounded batches of `CRS_OCR_BATCH_SIZE` (default 16) — rasterize batch → `walk_chain` → free images → next batch (peak memory = one batch, independent of length; per-page results unchanged). Each completed batch is persisted as a raw-zone shard `{document_id}/extract/batch-{start:05d}.json`; on job re-claim, existing shards are skipped/loaded so a crash resumes from the first missing batch (shard existence = resume marker, **no new table/migration**). All batches present → assemble ordered pages → `segment()` once → single final `extracted.json` (downstream shape unchanged; per-doc artifact sharding deferred to pre-prod). Oversized guardrail: page count read cheaply first; > `CRS_EXTRACT_MAX_PAGES` (default 1000) → **`extract_hold`** reason `oversized` (fail-closed, human-routed; distinct from the confidence hold via a `reason` field). Per-batch checkpoint audit event added alongside existing per-page attempt events. Fast path streams pages but needs no checkpoint (cheap); guardrail still applies. Intra-batch page parallelism = pre-prod knob, not POC. **Implementation owned by a future Claude Code session** — follow `/pipeline-stage` (batched-input section) + `/self-evaluate` |

## Current status

**ALL PHASES COMPLETE — G0–G7 PASSED** (`docs/gates/`; G7 lists two
presenter rehearsal items: scale corpus to ~100 docs, two cold-start
dry-runs). POC measured numbers are in `docs/gates/G7_report.md`; demo
script in `docs/demo_script.md`. Auth: JWT via `/auth/login` (seed:
`uv run python -m backend.seed_users`; roles reviewer/admin; Cognito-shaped
seam in `backend/auth.py`). Review API under `/review/*` — the decision
endpoint is the ONLY path to approved/rejected (reviewer role + rationale
mandatory; pipeline can never touch terminal decisions). React SPA served
at :8000 from the backend image (host port 8001 in compose); the contract
page is a three-pane review reading left to right: **reference template** |
masked contract | review brief. The left pane answers "compared against
what" — it serves
`reference_template` from `/review/contracts/{id}` (`_reference_template` →
`template_diff.compare_to_template`, recomputed from the masked artifact per
request, no new table) — every standard clause in template order with its
status (standard/borderline/deviation/missing/extra), similarity, and whether
it reached the STRONG model. **Per-contract verdicts render on the contract
pane only** (chip + similarity + "sent to the model"); the template pane stays
the unannotated source of truth, its sole exception being a `not in this
contract` marker on omitted clauses, which have no contract clause to sit on.
Clicking a clause in either pane highlights its counterpart; a
`template:<family>:<heading>` citation jumps to the standard wording that is
absent. LLM: containers use the direct API with
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
--extra ml`. OCR confidence chain is implemented (Decision Log row "OCR",
design §3.2/§4/§5.2): `extraction/ocr_engines.py` + `ocr_path.walk_chain` +
`run_extract` + `ExtractHold`/migration 0007 + `api/extract.py`; verified on a
scanned golden doc (Tesseract conf 0.946) with graceful skip of the absent
engines. Large scans (100s of pages) run through the **batched, checkpointed**
OCR path (Decision Log "Large-document extraction", design §3.2): bounded
per-batch rasterization (`CRS_OCR_BATCH_SIZE`), raw-zone batch checkpoints for
mid-document resume, and an oversized guardrail (`CRS_EXTRACT_MAX_PAGES` →
`extract_hold` reason `oversized`); verified on a real 6-page scan. Next:
validate the PaddleOCR/EasyOCR adapters + wire Docling
confidence at pre-prod under `--extra ocr`. `main.py`/`ppt_extract.py` at repo
root are scratch.

## Stack & layout

- `backend/` — uv project (workspace member): FastAPI (`src/backend/main.py`),
  settings (`config.py`, env prefix `CRS_`), SQLAlchemy (`db.py`), audit
  writer (`audit.py`), Alembic migrations (`alembic/`), tests (`tests/`,
  invariant suite in `tests/invariants/`).
- `frontend/` — React SPA (Vite + TypeScript).
- `docker-compose.yml` — the single environment definition: Postgres+pgvector,
  MinIO (buckets raw/masked/audit auto-created), Presidio analyzer,
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
