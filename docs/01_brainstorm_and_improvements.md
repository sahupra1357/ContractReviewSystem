# Brainstorm & Efficiency Improvements

**Project:** AI Contract Review Co-Pilot
**Scope basis:** Confirmed POC parameters (see Decision Log in CLAUDE.md)
**Date:** 2026-07-05

---

## 1. Confirmed operating context

| Parameter | Value |
|---|---|
| POC corpus | 100 test contracts (bulk-loaded), trickle ~10/day thereafter |
| Design-for scale | 10K near-term, millions long-term |
| Review SLA | Minutes per AI analysis; 1-day human turnaround |
| Reviewers | 10 (in-house legal), goal = **reduce review time**, not headcount |
| Sources (POC) | Authenticated multi-file upload page via connector interface; DMS + shared filesystem at pre-prod; expandable |
| Compliance | SOX-aware (audit-ready structure; certification post-POC) |
| Versioning | Latest version only (upgrade path documented) |
| Platform | Local Docker, AWS-shaped (1:1 production mapping) |
| UI | React SPA |
| Governance | Human-in-the-loop mandatory; zero auto-approvals |

---

## 2. The core insight: the bottleneck is the human, not the machine

At millions of documents the pipeline (OCR → mask → index → analyze) scales
horizontally — it is an engineering cost problem, not a feasibility problem.
What does **not** scale horizontally is 10 reviewers. Every efficiency
improvement below is judged by one question:

> Does it reduce the minutes a reviewer spends per contract, or reduce the
> compute cost per document — without weakening the security posture?

---

## 3. Improvements to the reviewed architecture

### 3.1 Content-hash deduplication at landing (HIGH impact at scale)
Enterprise corpora contain heavy duplication: renditions, re-sends, scanned
copies of the same signed contract. A SHA-256 content hash at the S3-landing
stage, checked before any OCR, skips duplicates entirely.
- **At millions of docs:** commonly 20–40% of raw volume is duplicate or
  near-duplicate; this is compute you never spend.
- **POC cost:** trivial (one hash + one index lookup).

### 3.2 Born-digital fast path — don't OCR what already has text (HIGH impact)
The reviewed design routes everything through GPU OCR. Most modern contracts
(DocuSign output, DMS-generated PDFs) are born-digital with an embedded text
layer. Add a classifier step:
- **Born-digital PDF/DOCX** → direct text extraction (cheap, exact, CPU-only).
- **Scanned/image PDF** → GPU OCR path (PaddleOCR/Docling).
At scale this typically cuts OCR compute 60–80% and *improves* accuracy on
the fast path (no OCR errors).

### 3.3 Template-deviation analysis (HIGH impact on review time)
Most enterprise contracts derive from a small set of standard templates.
Instead of asking the LLM to analyze a whole contract:
1. Detect the closest template / contract family (embedding similarity).
2. Diff the contract against the template at clause level.
3. LLM analyzes **only the deviations** and flags non-standard clauses.
- **Reviewer benefit:** "here is what is unusual in this contract" is exactly
  what a lawyer wants; reading time drops from reading everything to
  verifying deviations.
- **Cost benefit:** far fewer LLM tokens per contract; compounds with prompt
  caching (the template context is the cached prefix).
- **POC:** demonstrate with 2–3 contract families in the 100-doc corpus.

### 3.4 Risk-ranked review brief, not raw analysis (HIGH impact on review time)
The co-pilot's output to the reviewer should be a structured **review brief**:
- Risk-ranked findings (clause deviations, missing clauses, unusual terms).
- Extracted key terms (parties, dates, amounts, obligations, renewal terms).
- A suggested decision **with citations back to exact source passages** —
  every claim clickable to the underlying text.
- The reviewer verifies instead of reads. This is the single biggest lever on
  the "reduce review time" goal.

### 3.5 Priority triage queue (MEDIUM impact, essential at scale)
With 10 reviewers × ~1-day turnaround, throughput is ~10 contracts/day
sustained. At scale, ordering matters more than raw speed:
- Queue ordered by urgency (renewal/expiry dates, deal value, requestor SLA),
  not FIFO.
- Confidence-based depth: standard, high-confidence contracts get a short
  brief; unusual/low-confidence contracts get full annotation. **Never**
  auto-approve — vary the depth of assistance, not the presence of the human.

### 3.6 Graph-lite before Neptune (MEDIUM impact, big cost deferral)
The reviewed design includes Neptune for multi-hop retrieval. Confirmed use
case is **retrieval only** (not compliance reporting). At 10K–1M documents,
parties/obligations/amendments relationships model cleanly as relational
tables in PostgreSQL; 1–2-hop queries are fast with ordinary indexes and
recursive CTEs.
- **POC:** entity/relationship tables in Postgres ("graph-lite").
- **Gate to Neptune:** adopt only when measured query patterns show ≥3-hop
  traversals or graph-native algorithms are actually needed. This is a
  validated-need decision, not a default.

### 3.7 One store for hybrid retrieval in the POC (MEDIUM)
Production design: Aurora pgvector + OpenSearch. POC: **Postgres alone** does
both — pgvector for dense vectors, native full-text search (tsvector/BM25-ish)
for keywords, fused with reciprocal-rank fusion. Same hybrid-retrieval
concept, one fewer system, direct upgrade path to Aurora + OpenSearch.

### 3.8 Embedding cache keyed by chunk hash (LOW effort, compounding savings)
Chunks repeat across contract versions and templates. Cache embeddings by
content hash: re-ingestion and template-heavy corpora skip recomputation.

### 3.9 Golden evaluation set + feedback loop (HIGH impact on trust)
The reviewed design defines gates (e.g., PII recall ≥ 0.98) but no measurement
harness. Add from day one:
- A **golden set**: 20–30 contracts, hand-labeled for PII entities, key terms,
  and known issues.
- Automated eval runs for: extraction accuracy, PII recall/precision,
  retrieval quality, and analysis groundedness.
- **Feedback loop:** every reviewer correction (rejected finding, edited term)
  is logged as labeled data — this becomes the tuning corpus and the
  post-POC improvement engine.
- For the C-level demo, real measured numbers ("PII recall 0.98 on our own
  labeled set") are far more credible than citing industry benchmarks.

### 3.10 Defer ElastiCache/Redis and A2I (POC simplification)
- Response caching: add when measurements show need; premature at 100 docs.
- A2I: the review workflow lives in our own React app + API with a full audit
  trail; A2I adds AWS coupling without POC benefit. Revisit for production.

---

## 4. What we deliberately keep from the reviewed design

- **PII gate is absolute** — masking before any embedding/indexing/LLM call.
  Presidio self-hosted, recall-tuned, with the ≥0.98 gate measured on the
  golden set.
- **Human approval on every decision** — enforced in the workflow state
  machine; there is no code path to auto-approve.
- **Clause-level chunking** — legal context preserved; also the unit for
  template diffing (3.3) and citations (3.4).
- **Reranking** — cross-encoder rerank after hybrid retrieval; cheap and
  high-value.
- **Tiered model routing** — cheap/fast model for classification and
  extraction, strongest model for legal analysis.
- **Full audit trail** — every ingestion event, pipeline stage, AI suggestion,
  and human decision recorded immutably (SOX-aware from day one).

---

## 5. Scale path summary (100 → 10K → millions)

| Concern | POC (100) | 10K | Millions |
|---|---|---|---|
| Storage | MinIO (local S3) | S3 | S3 + lifecycle tiers |
| OCR | 1 worker, CPU/GPU | GPU autoscaling group | Fleet + spot; dedup + fast path cut load 60%+ |
| Vector/keyword | Postgres (pgvector + FTS) | Aurora pgvector | Aurora + OpenSearch hybrid |
| Graph | Postgres graph-lite | Postgres graph-lite | Neptune **if** multi-hop need proven |
| LLM | Claude API (Bedrock-shaped) | Bedrock + prompt caching | Bedrock + caching + tiered routing + batch |
| Queue | Postgres job table | SQS | SQS + Step Functions |
| Review capacity | 10 reviewers | Triage queue + confidence-based depth | Same + workload analytics |

---

## 6. Risks called out (carried into the design document)

1. **PII recall ≥ 0.98** — de-risked by design (2026-07-05, owner decision;
   fits the real-estate context where counterparties are known in advance):
   deterministic master-table masking is the only masking authority, and a
   fail-closed Presidio tripwire **halts** any document with a possible
   unregistered entity (`pii_hold`) instead of guessing. Residual risks are
   operational: master-table freshness and tripwire false-alarm volume —
   both measured at G3.
2. **OCR quality on poor scans** — golden set must include bad scans.
3. **LLM hallucination** — mitigated by grounding, mandatory citations, and
   the human gate; measured by groundedness eval.
4. **DMS specifics unknown** — POC treats DMS as an export-drop behind the
   connector interface; the actual DMS product/API must be confirmed
   (open question OQ-1 in the design document).
