# SDLC Plan — Contract Review Co-Pilot POC

**Scope:** POC (100 contracts, local Docker AWS-shaped, React SPA, C-level demo)
**Governance rule:** every phase ends with a **gate**; the next phase does not
start until the gate passes and is recorded in the decision log.
**Date:** 2026-07-05

---

## 1. SDLC components mapped to this project

| SDLC discipline | How it applies here |
|---|---|
| Requirements engineering | Confirmed POC parameters (CLAUDE.md decision log); golden-set labeling defines "correct" |
| Architecture & design | `docs/03_design_document.md` — reviewed and feasibility-verified before any code |
| Implementation | Phased pipeline stages (below); Python backend, React frontend; connector interface for sources |
| Quality assurance | Unit + integration tests per stage; **eval harness** on the golden set (extraction, PII recall, retrieval, groundedness) |
| Security engineering | PII gate, RBAC, audit trail designed in from Phase 0; gate checklists per phase (`security-gate` skill) |
| Configuration management | Git; docker-compose as the single environment definition; seeded demo data reproducible from scratch |
| Deployment | `docker compose up` = full stack; AWS mapping documented for production path |
| Operations & monitoring | Pipeline status dashboard, per-stage metrics, structured logs (CloudWatch-shaped) |
| Documentation | Design doc, decision log, runbooks in skills; demo script |

---

## 2. Phase plan

Durations are indicative for a small team (1–3 engineers); adjust to staffing.
Total: **~8–10 weeks** to demo-ready.

### Phase 0 — Foundations (Week 1)
- Repo layout, `uv` Python project, React app scaffold, docker-compose skeleton
  (Postgres+pgvector, MinIO, Presidio service).
- CI: lint, type-check, unit tests.
- **Golden set assembly begins** (20–30 contracts labeled for PII + key terms
  + known issues) — this is on the critical path for Phases 2–4 gates; start now.
- Audit-event schema defined (SOX-aware from the first table).
- **GATE G0:** stack boots with one command; CI green; audit schema reviewed;
  golden-set labeling plan agreed.

### Phase 1 — Ingestion & connectors (Week 2)
- Connector interface (abstract) + **UploadConnector**: authenticated
  multi-file upload API (the React upload page itself lands in Phase 6; until
  then an API client / minimal form drives it). DMS and shared-filesystem
  connectors deferred to pre-prod (OQ-1 resolution, 2026-07-05).
- Landing store (MinIO, KMS-shaped encryption config), SHA-256 dedup,
  document registry table, job queue (Postgres job table).
- Bulk load of the 100-contract corpus via multi-file upload + trickle mode
  (~10/day sim).
- **GATE G1:** 100 docs land exactly once (dedup proven with planted
  duplicates); every upload attributed to a user in the audit trail; adding a
  mock second connector requires no core changes.

### Phase 2 — Extraction (Weeks 3–4)
- Born-digital classifier → fast path (direct text) vs OCR path
  (PaddleOCR/Docling in a worker container).
- Layout-aware extraction: clause/section structure preserved.
- **Large-document handling (design doc §3.2, added 2026-07-15):** batched,
  checkpointed OCR — bounded peak memory (`CRS_OCR_BATCH_SIZE`), per-batch
  resume shards, `CRS_EXTRACT_MAX_PAGES` oversized guardrail → `extract_hold`.
- **GATE G2:** extraction accuracy on golden set meets threshold (target
  ≥95% text fidelity on born-digital, ≥90% on scans); clause boundaries
  correct on sampled review. **Large-doc check:** a multi-hundred-page scan
  extracts with peak memory bounded to ~`CRS_OCR_BATCH_SIZE` pages, and a
  worker killed mid-document resumes from the last checkpoint (no full
  re-OCR); an over-cap document parks in `extract_hold` (reason `oversized`).

### Phase 3 — PII gate (Weeks 4–5)
- **Deterministic masking (the only masking authority):** driven by the
  `pii_known_entities` **master table** (real Postgres table, maintained in
  advance) — exact + fuzzy/OCR-tolerant matching; recall 1.0 on registered
  entities by construction. Table version recorded per masking run.
- **Fail-closed tripwire:** Presidio as detector only (never masks). Any
  possible unregistered entity → document halts in `pii_hold`; human resolves
  (add to master table → re-mask, or dismiss with rationale). Unknown PII
  cannot flow downstream.
- Golden set must plant both registered and unregistered/novel PII to prove
  the tripwire halts correctly; masked store is the **only** input to all
  downstream stages (enforced structurally, not by convention).
- (Admin screen + hold-queue UI land in Phase 6; Phase 3 provides the table,
  the pipeline behavior, and a CLI/API path to resolve holds for testing.)
- **GATE G3 (hard gate):** PII recall ≥ 0.98 on the labeled golden set,
  measured on what reaches downstream (post-hold-resolution); zero unregistered
  planted entities pass unhalted; tripwire false-alarm rate reported
  (hold-queue burden per 100 docs).
  If not met: tune and iterate — downstream phases may build against
  synthetic/masked fixtures but nothing real flows past this gate.

### Phase 4 — Knowledge & index (Weeks 5–6)
- Clause-level chunking; embeddings (local BGE-M3 or API) with chunk-hash cache.
- Hybrid retrieval in Postgres (pgvector + FTS, rank fusion) + cross-encoder
  rerank.
- Graph-lite: parties / obligations / amendments / risk entities +
  relationships as relational tables.
- **GATE G4:** retrieval quality on golden-set queries (e.g., recall@10 ≥
  target agreed at G2); entity extraction spot-check passes.

### Phase 5 — AI analysis (Weeks 6–7)
- Template/family detection + clause-level deviation diff.
- Review-brief generation: risk-ranked findings, key terms, suggested decision,
  **mandatory citations** to source passages.
- Tiered model routing (cheap model: classification/extraction; strong model:
  legal analysis). Claude API via Bedrock-shaped adapter.
- Groundedness eval: every finding must map to a real passage.
- **GATE G5:** analysis of golden-set contracts finds ≥ agreed % of the
  labeled known issues; zero uncited findings; per-contract analysis completes
  within the minutes-level SLA.

### Phase 6 — Review application (Weeks 7–8)
- FastAPI backend: auth (JWT, Cognito-shaped), RBAC (reviewer/admin), review
  workflow state machine (`ingested → analyzed → in_review → approved |
  rejected | changes_requested`), triage queue ordering.
- React SPA: **multi-file upload page** (POC ingestion entry point), queue
  view, contract view (brief + source side-by-side, clickable citations),
  approve/reject with mandatory rationale, **PII master-table admin screen**
  and **PII hold queue** (resolve tripwire flags), audit view.
- **No auto-approve code path exists.** Decisions require an authenticated
  human + rationale; every action audited.
- **GATE G6:** end-to-end walkthrough — ingest → brief → human decision →
  audit record; zero auto-approvals verifiable from the audit trail alone;
  RBAC enforced.

### Phase 7 — Hardening & demo prep (Weeks 9–10)
- Seed full 100-contract corpus; metrics dashboard (docs processed, PII recall,
  time-per-review before/after, cost per contract).
- Demo script: live ingest of a new contract → analysis in minutes → reviewer
  approves in the UI → audit trail shown.
- Failure-mode rehearsal (LLM down, bad scan, PII edge case) + fallbacks.
- Security review pass (`security-gate` skill, full checklist) + C-level deck
  updates with **measured** numbers.
- **GATE G7 (demo readiness):** cold-start `docker compose up` → scripted
  demo runs clean twice in a row; every claim in the deck traceable to a
  measured result.

---

## 3. Cross-phase workstreams

- **Golden set & eval harness** — starts Phase 0, used by every gate.
- **Audit trail** — every stage writes events from its first commit.
- **Decision log** — every dilemma resolved with the product owner is recorded
  in CLAUDE.md (per project rule: no assumptions).
- **AWS mapping** — each component built notes its production AWS equivalent
  (kept current in the design doc §7).

## 4. Definition of done (POC)

1. 100 contracts ingested, masked, indexed, analyzed; new docs handled at
   ~10/day trickle.
2. AI analysis per contract in minutes; review brief with citations.
3. 10-reviewer workflow with triage queue; 1-day turnaround demonstrated.
4. PII recall ≥ 0.98 measured; zero auto-approvals provable from audit trail.
5. SOX-aware audit + compliance roadmap document for the C-level deck.
6. Scale-path narrative (100 → 10K → millions) with the AWS mapping table.
