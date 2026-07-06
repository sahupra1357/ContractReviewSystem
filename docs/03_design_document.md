# Design Document — Contract Review Co-Pilot POC

**Version:** 1.0 (POC)
**Status:** Awaiting product-owner approval — no implementation until approved
**Date:** 2026-07-05
**Companion docs:** `01_brainstorm_and_improvements.md`, `02_sdlc_plan.md`,
`../project_document/AI_Contract_CoPilot_Security_Review.txt`

---

## 1. Goals & non-goals

### Goals (POC)
- Prove an AI-assisted contract review workflow end-to-end: ingest → extract →
  mask PII → index → analyze → human review → auditable decision.
- Reduce reviewer time per contract via risk-ranked, citation-backed review briefs.
- Demonstrate the security posture in miniature: absolute PII gate, zero
  auto-approvals, full audit trail (SOX-aware).
- Run entirely on a local Docker stack whose every component has a named AWS
  production equivalent (§7).
- Convince a C-level audience with **measured** numbers on our own corpus.

### Non-goals (POC — explicitly deferred)
- Full SOX certification (SOX-aware structure only; roadmap included).
- Contract version history (latest-only; upgrade path in §5.4).
- DMS / shared-filesystem / SharePoint / DocuSign / Email connectors — POC
  ingests via an authenticated multi-file **upload page**; source-system
  connectors arrive at pre-prod behind the same interface (proves expandability).
- Neptune, OpenSearch, ElastiCache, A2I (graph-lite and Postgres hybrid
  retrieval instead; adoption criteria documented).
- Multi-tenant / customer-facing operation (in-house legal only).

---

## 2. Architecture overview

Local Docker Compose stack, shaped 1:1 to the reviewed AWS architecture:

```
 SOURCES                    PIPELINE (async workers, job queue)              APPLICATION
┌──────────────┐   ┌────────────────────────────────────────────────┐   ┌──────────────────┐
│ Upload page  │   │  Landing     Extract      PII GATE    Index    │   │  FastAPI backend │
│ (multi-file, ├──▶│  (MinIO,  ─▶ (fast path ─▶ (Presidio ─▶ (chunk,│   │  auth·RBAC·audit │
│ authenticated│   │  dedup,      or OCR        mask;      embed,   │   │        ▲         │
│ [DMS: preprod]   │  registry)   worker)       recall-    hybrid   │   │        │         │
└──────────────┘   │                            tuned)     search,  │   │  React SPA       │
                   │                              │        graph-   │   │  queue · brief · │
                   │              RAW stays here ─┘        lite)    │   │  approve/reject  │
                   │                                         │      │   └──────────────────┘
                   │                                     Analyze    │            ▲
                   │                                  (template diff│            │
                   │                                   + LLM brief, ├────────────┘
                   │                                   citations)   │   review briefs
                   └────────────────────────────────────────────────┘
                        Postgres: registry · jobs · chunks · vectors ·
                        entities/graph-lite · decisions · AUDIT (append-only)
```

**Invariants (enforced structurally, not by convention):**
1. **PII gate is absolute** — the masked store is a separate schema/bucket;
   indexing, embedding, and LLM stages have no read access to raw text.
2. **No auto-approve** — the workflow state machine has no transition to
   `approved`/`rejected` except via an authenticated human action carrying a
   rationale.
3. **Everything audited** — every stage transition, AI suggestion, and human
   action appends to an append-only audit table (no UPDATE/DELETE grants).

---

## 3. Component design

### 3.1 Connectors (Ingestion)
- **Interface:** `poll() → [SourceDocument]`, `fetch(id) → bytes + metadata`,
  `ack(id)`. One abstract base; each source is a plug-in.
- **POC implementation (per OQ-1 resolution, 2026-07-05):** UploadConnector —
  a multi-file upload page in the review app (React) posting to an
  authenticated upload API. Uploaded files enter the exact same landing →
  dedup → registry path as any connector; each upload is attributed to the
  uploading user in the audit trail. Bulk-loading the 100-contract corpus and
  the ~10/day trickle both go through this path (multi-select upload).
- **Deferred to pre-prod:** DMSConnector and shared-filesystem connector —
  implemented behind the same interface when the pre-prod environment and the
  real DMS access method are available.
- **Dedup:** SHA-256 of content checked against the registry before any
  processing; duplicates recorded (audit) and skipped.
- **Modes:** bulk load (100-doc corpus) and trickle (~10/day).
- **AWS mapping:** Transfer Family/DataSync (DMS), AppFlow (SharePoint),
  SES (email), SQS webhooks (DocuSign) — all behind the same interface.

### 3.2 Extraction
- **Classifier:** born-digital (has text layer) vs scanned.
- **Fast path:** direct text + layout extraction (CPU).
- **OCR path:** PaddleOCR/Docling worker container (GPU if available; CPU
  acceptable at POC volume).
- **Output:** structured document — sections/clauses with stable IDs,
  page/offset provenance for citations.

### 3.3 PII Gate — deterministic-primary, fail-closed (updated 2026-07-05
per product-owner decision)

**Context that drives this design:** the business is real estate —
counterparties are known well in advance, so the PII inventory is proactively
maintainable; and a single PII miss is very costly. Therefore: deterministic
masking is the **only** masking authority, and anything it doesn't recognize
**stops the document** rather than being guessed at.

**Step 1 — Deterministic masking from the PII master table (the authority).**
- `pii_known_entities` is a real Postgres table **from the POC** (not
  deferred): party names, aliases, signatories, identifiers/patterns —
  maintained *in advance* of contract arrival via an **admin screen** in the
  React app (RBAC: admin; every edit audited; table version recorded on every
  masking run for reproducibility).
- The masking script replaces every occurrence of a registered entity —
  recall 1.0 on registered entities by construction. Matching is exact
  **plus fuzzy/normalized** (case, spacing, punctuation, common OCR mutations
  like `J . Rivera`), because OCR output mutates strings.

**Step 2 — Probabilistic tripwire (Presidio, detector only — it never masks).**
Presidio (custom recognizers, recall-tuned) scans the deterministically
masked text. Its findings do not trigger automatic masking; instead:
- **Zero flags** → document proceeds downstream.
- **Any flag of a possible unregistered entity** → document halts in
  **`pii_hold`**. A human reviews the flag: real PII → add to the master
  table, document re-masks and re-checks; false alarm → dismiss with
  rationale (audited) and the document proceeds.
This is **fail-closed**: unknown potential PII can never flow downstream —
a false alarm costs minutes; a real catch prevents the high-cost miss.
Presidio false-positive tuning matters for hold-queue volume, not for safety.

**Step 3 — Backstops (unchanged).** Storage scanning (Macie-shaped,
production), model-traffic guardrails, and mandatory human review of every
contract decision.

- Masked output written to the masked store; the entity map (tagged
  registered-match vs tripwire-confirmed) kept in the restricted
  `pii_entity_map` schema (reveal under RBAC only, audited).
- **Gate G3:** recall ≥ 0.98 on golden-set labels, measured on what reaches
  downstream (i.e., after hold-queue resolution). The golden set must plant
  both registered entities **and** unregistered/novel PII to prove the
  tripwire halts correctly. Additionally measured: tripwire false-alarm rate
  (hold-queue burden per 100 docs).
- **The C-team claim this design supports:** "no document reaches the AI with
  PII our controls did not either mask or stop" — deterministic control plus
  fail-closed exception handling, with the honest note that the tripwire's
  detector is still probabilistic, which is why the hold queue defaults to
  stopping.

### 3.4 Knowledge & Index
- **Chunking:** clause-level (aligned to §3.2 structure), chunk-hash embedding cache.
- **Embeddings:** BGE-M3 self-hosted (or API fallback) — masked text only.
- **Retrieval:** Postgres hybrid — pgvector (dense) + native FTS (sparse),
  reciprocal-rank fusion, then cross-encoder rerank.
- **Graph-lite:** `entities` + `relationships` tables (party, obligation,
  amendment-of, risk) supporting 1–2-hop queries via SQL. Neptune adoption
  criteria: proven ≥3-hop query need at scale.

### 3.5 AI Analysis
- **Template/family detection:** embedding similarity to known families;
  clause-level deviation diff against the family template.
- **Review brief generation** (strong model): risk-ranked findings, key terms,
  suggested decision + rationale; **every finding must cite chunk IDs** —
  uncited findings are rejected by a groundedness check before display.
- **Tiered routing:** cheap/fast model for classification & term extraction;
  strongest model for legal analysis. Prompt caching on template/family context.
- **LLM adapter — multi-provider, configurable (updated 2026-07-06 per
  product-owner decision):** one `LLMClient` interface; provider selected by
  configuration (`CRS_LLM_PROVIDER`), never hardcoded. Masked text only ever
  reaches any provider (invariant #1 applies regardless of vendor).

  | Provider | Client path | Notes |
  |---|---|---|
  | `anthropic` (**default**) | official `anthropic` SDK (Messages API) | honors `ANTHROPIC_BASE_URL` (local proxy) ; default models: strong `claude-opus-4-8`, fast `claude-haiku-4-5` |
  | `bedrock` (**production**) | `AnthropicBedrockMantle` (`anthropic[bedrock]`) | `anthropic.`-prefixed model ids, AWS region req.; the in-VPC PrivateLink path of the security review |
  | `openai`, `nvidia` (Nemotron), `mistral`, `minimax`, `kimi` (Moonshot), `qwen` (DashScope) | one OpenAI-compatible chat-completions client | per-provider default base URLs; model/key via config; default model ids are placeholders to verify against each vendor's current catalog |

  Tiered routing stays provider-agnostic: `llm_model_strong` (legal analysis)
  and `llm_model_fast` (classification/extraction) resolve per provider.
  Guardrails-equivalent checks (injection heuristics on contract text, output
  grounding/citation validation) live in the analysis layer **above** the
  adapter, so they apply identically to every provider.

### 3.6 Review Application
- **Backend:** FastAPI — auth (JWT, Cognito-shaped), RBAC (reviewer, admin),
  workflow state machine, triage-queue ordering (urgency metadata → priority),
  audit append on every action.
- **Frontend:** React SPA — multi-file upload page; triage queue; contract
  view with brief and source side-by-side and clickable citations; approve /
  reject / request-changes with mandatory rationale; **PII master-table admin
  screen** (add/edit registered entities; admin role; audited) and **PII hold
  queue** (resolve tripwire flags); audit-trail view; pipeline/metrics
  dashboard for the demo.

---

## 4. Workflow state machine

```
ingested → extracted → masking ─┬→ masked → indexed → analyzed → in_review
                                │                                   │ (human, authenticated,
                                └→ pii_hold (tripwire flag)         │  rationale required)
                                     │ (human: add to master table  │
                                     │  → re-mask; or dismiss       │
                                     │  false alarm w/ rationale)   │
                                     └──────→ masking (re-run)      │
                                                    ┌───────────────┼────────────────┐
                                                approved         rejected     changes_requested → (re-analyze) → in_review
```
- Transitions into `approved`/`rejected` exist **only** on the
  human-decision API path. Pipeline code cannot reach them.
- Failures at any stage → `failed_<stage>` with error detail, visible on the
  dashboard, retryable.

---

## 5. Data model (Postgres, logical)

### 5.1 Core
- `documents` — registry: id, source, source_ref, content_sha256 (unique),
  status, urgency metadata, timestamps. *(Latest-only: re-ingest of a changed
  document replaces derived data; see §5.4.)*
- `jobs` — pipeline queue: document_id, stage, state, attempts, error.
- `clauses/chunks` — clause id, document_id, section path, masked text,
  page/offset provenance, chunk hash.
- `embeddings` — chunk_id, vector (pgvector), model, keyed by chunk hash.
- `entities`, `relationships` — graph-lite (§3.4).
- `analyses` — per document: findings[] (risk rank, description, cited chunk
  ids), key terms, suggested decision, model + prompt version, latencies, cost.
- `decisions` — document_id, reviewer_id, action, rationale (required), timestamp.

### 5.2 Security
- `users`, `roles` — RBAC.
- `pii_entity_map` — restricted schema; original↔mask mapping, tagged
  registered-match vs tripwire-confirmed; access audited.
- `pii_known_entities` — the PII **master table** (a real table from the POC):
  party names, aliases, signatories, identifiers/patterns; maintained in
  advance via the admin screen (audited edits); every masking run records the
  table version used. Post-POC: fed automatically by vendor/customer onboarding.
- `pii_holds` — tripwire flags: document_id, flagged span/entity type,
  resolution (added-to-master | dismissed), resolver, rationale, timestamps.
- `audit_events` — **append-only** (INSERT-only grants): actor (human/system),
  action, object, before/after state hash, timestamp. SOX-aware core.

### 5.3 Storage buckets (MinIO → S3)
- `raw/` — originals, encrypted, pipeline has write-once access; only the
  extraction stage reads.
- `masked/` — post-gate artifacts; the only bucket downstream stages can read.
- `audit/` — exported audit bundles.

### 5.4 Versioning upgrade path (post-POC)
Add `version` + `supersedes_id` to `documents`; keep derived rows per version;
add `AMENDS` edges in graph. No POC schema decision blocks this.

---

## 6. API surface (indicative, not final)

- `POST /ingest/bulk`, `POST /ingest/trickle` — operator endpoints.
- `GET /queue` — triage-ordered review queue (RBAC: reviewer).
- `GET /contracts/{id}` — document + brief + citations.
- `POST /contracts/{id}/decision` — approve/reject/changes; body requires
  rationale; 403 for non-reviewers; always audited.
- `GET /contracts/{id}/audit`, `GET /metrics` — audit and demo dashboard.

---

## 7. AWS production mapping

| POC component | Production (per security review) |
|---|---|
| MinIO buckets | S3 + KMS CMK |
| Postgres pgvector + FTS | Aurora PostgreSQL pgvector (+ OpenSearch at scale) |
| Postgres job table | SQS + Step Functions + EventBridge |
| Graph-lite tables | Neptune (only if ≥3-hop need proven) |
| Presidio container | Presidio on ECS/EKS in-VPC |
| OCR worker container | PaddleOCR/Docling on GPU ECS/EKS |
| Claude API adapter | Bedrock (Claude) via PrivateLink + Guardrails |
| FastAPI + JWT | API Gateway + Lambda/ECS + Cognito |
| React (Vite dev) | Amplify behind WAF + internal ALB |
| Structured logs / metrics page | CloudWatch, CloudTrail, GuardDuty, Security Hub, Macie |
| .env secrets (POC only) | Secrets Manager with rotation |

---

## 8. Feasibility verification

| # | Component / claim | Evidence | Verdict | Residual risk |
|---|---|---|---|---|
| F1 | Clause-aware extraction of PDFs/DOCX | Docling/PaddleOCR are mature OSS with documented table/layout support; born-digital fast path is standard practice | **Feasible** | Poor scans degrade quality → golden set includes bad scans; G2 measures it |
| F2 | PII recall ≥ 0.98 (fail-closed gate §3.3) | Deterministic master-table masking = recall 1.0 on registered entities; tripwire halts documents with possible unregistered PII, so unknowns stop rather than pass — downstream recall is protected by construction | **Feasible — risk transformed (was top risk)** | Risk moves from silent misses to (a) master-table freshness — an operational duty suited to the real-estate advance-knowledge workflow — and (b) tripwire false-alarm volume clogging the hold queue; both measured at G3 |
| F3 | Hybrid retrieval in one Postgres | pgvector + FTS + RRF is a well-trodden pattern at 10K–1M chunk scale | **Feasible** | At millions of docs move to Aurora+OpenSearch (mapped) |
| F4 | Graph-lite replaces Neptune for POC | Confirmed use = retrieval only; 1–2-hop relational queries at 10K scale are trivial | **Feasible** | Re-evaluate on measured query patterns (§3.4 criteria) |
| F5 | Minutes-level analysis SLA | Template-diff + tiered routing keeps token volume low; single-contract latency dominated by 1–3 LLM calls | **Feasible** | Cold-cache worst case measured in Phase 7 rehearsal |
| F6 | Review-brief groundedness | Citation-required generation + programmatic grounding check; human gate catches residue | **Feasible** | Hallucination risk never zero → mandatory human sign-off (kept) |
| F7 | Zero auto-approval, provable | State machine has no programmatic path to approved; audit is append-only | **Feasible by construction** | — |
| F8 | SOX-aware audit trail | Append-only event table + actor attribution + decision rationale is standard | **Feasible** | Formal SOX certification deferred (confirmed scope) |
| F9 | Local→AWS portability | Every component chosen has a named managed equivalent (§7); adapters isolate Claude API vs Bedrock | **Feasible** | Bedrock model/feature parity to be validated in production phase |
| F10 | 100 docs bulk + 10/day trickle on one machine | Trivial volume; heaviest step (OCR) worst-case minutes/doc on CPU | **Feasible** | None material |

**Overall verdict: the POC is feasible as designed.** The single hardest
target is F2 (PII recall ≥ 0.98); it is gated, measured, and backstopped —
and it is the right thing to be hard on.

---

## 9. Open questions (tracked; none block Phase 0)

- **OQ-1 — RESOLVED (2026-07-05):** POC ingests via an authenticated
  multi-file upload page (UploadConnector, §3.1); DMS and shared-filesystem
  integration deferred to the pre-prod environment. The DMS product name and
  access method are still needed **at pre-prod time** — carried forward as a
  pre-prod prerequisite, no longer a POC blocker.
- **OQ-2 — RESOLVED (2026-07-05):** golden set = **synthetic contracts**.
  We generate 20–30 realistic fake contracts (real template structure, fake
  parties, planted fake PII, deliberately planted issues) — labels known by
  construction, no real PII handled during the POC. Stored under
  `golden_set/` with labels alongside each document. Real-contract validation
  (a small anonymized set labeled by legal) moves to pre-prod. Demo deck must
  state clearly that POC metrics are measured on the synthetic labeled set.
- **OQ-3 — RESOLVED (2026-07-06):** three real-estate template families for
  the synthetic corpus and template-diff demo: **lease agreement**,
  **property purchase agreement**, **vendor/property-services agreement**.
- **OQ-4 — Reviewer rubric:** what fields must a decision rationale capture
  for legal ops (free text vs structured reasons)?
- **OQ-5 — Demo environment:** laptop vs internal VM for the C-level demo;
  GPU available or CPU-only OCR?

---

## 10. Approval

This design is implemented only after product-owner sign-off. Any deviation
during implementation that changes an invariant (§2), a gate, or a confirmed
decision goes back to the product owner with evidence and a suggestion first
(project rule: no assumptions).
