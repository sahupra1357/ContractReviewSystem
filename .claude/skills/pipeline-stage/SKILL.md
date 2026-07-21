---
name: pipeline-stage
description: Implement or modify a contract-pipeline stage (ingest, extract, PII-mask, index, analyze) following the design document, without breaking the security invariants. Use when adding a stage, changing stage logic, or wiring a new stage into the job queue.
---

# Implementing a pipeline stage

Authoritative reference: `docs/03_design_document.md` (§3 components, §4 state
machine, §5 data model). If anything you need is not specified there, STOP —
present evidence + a suggestion to the product owner and get confirmation
(project rule: no assumptions). Record the outcome in CLAUDE.md's Decision Log.

## Step-by-step

1. **Locate the stage in the design.** Read the matching subsection of design
   doc §3 and the state machine in §4. Confirm the stage's input store, output
   store, and the `documents.status` transitions it owns.

2. **Check the invariants that apply:**
   - Stages downstream of the PII gate (index, analyze) may read **only** the
     masked store/schema. Verify your DB role and bucket permissions cannot
     see raw text — enforcement is structural, not convention.
   - No stage may write to `decisions` or transition a document to
     `approved`/`rejected`. Those belong exclusively to the human-decision API.
   - Every run appends `audit_events` rows: stage start, success/failure,
     counts, error detail. INSERT-only.

3. **Implement as a queue worker.** Stages consume from the `jobs` table
   (POC) — claim job → process → write outputs → update status → enqueue the
   next stage's job. Make it **idempotent**: re-running a job for the same
   document must not duplicate chunks/embeddings/entities (use content/chunk
   hashes and upserts).

4. **Failure handling.** On error: status `failed_<stage>`, error recorded on
   the job, audit event written. Never swallow exceptions; never skip a
   document silently.

   **Holds are not failures.** When a stage detects a *quality* problem that
   needs human judgment (unregistered PII → `pii_hold`; all OCR engines below
   the confidence threshold → `extract_hold`, design doc §3.2), it parks the
   document in the hold state instead of `failed_<stage>`. A hold is resolved
   only by an authenticated human with a mandatory rationale, the resolution
   is audited, and nothing retries out of a hold automatically. Follow this
   pattern for any new fail-closed check.

5. **Confidence-bearing sub-engines** (OCR is the model): when a stage
   fans out to interchangeable engines, put them behind one adapter that
   returns `(result, confidence)` with confidence normalized to 0–1 —
   an engine result without a confidence score is a defect. Chain order and
   the threshold come from `CRS_` config (`CRS_OCR_ENGINE_CHAIN`,
   `CRS_OCR_CONFIDENCE_THRESHOLD`), never hardcoded, and every engine attempt
   is an audit event.

6. **Large inputs — batch and checkpoint, never materialize the whole thing.**
   A stage that fans out over pages/chunks (OCR is the model, design doc §3.2)
   must not load an entire multi-hundred-page document into memory at once.
   Follow the batched/checkpointed pattern:
   - Process in bounded batches sized from `CRS_` config (`CRS_OCR_BATCH_SIZE`);
     free each batch's heavy objects (rasterized images) before the next.
     Peak memory must be one batch, not the whole document.
   - Persist each completed batch as a **raw-zone** shard
     (`{document_id}/<stage>/batch-{start:05d}.json`, pre-PII-gate — invariant
     #1 still holds; downstream never reads shards). On job re-claim, skip and
     load batches whose shard already exists — this is what makes a crash/
     timeout resume from the last batch instead of re-running from the start,
     and it needs no new table (shard existence is the resume marker). Keep the
     final assembled artifact's shape unchanged so downstream stages don't move.
   - Add a fail-closed guardrail for pathological sizes: over
     `CRS_EXTRACT_MAX_PAGES` → `extract_hold` (reason `oversized`), same hold
     mechanics as §4, never a silent unbounded run.
   - Emit one checkpoint audit event per batch (in addition to per-item events)
     so progress is observable; keep results deterministic (preserve
     page/item order via the batch's start offset).

7. **Tests before done:**
   - Unit tests for the stage logic.
   - Integration test: document enters in the prior status, leaves in the
     next status, audit rows exist, re-run is idempotent.
   - If the stage affects extraction/PII/retrieval/analysis quality, run the
     golden-set eval and compare to the previous baseline — regressions block.

8. **Update docs.** If the stage's behavior deviates from design doc §3 in any
   confirmed way, update the design doc in the same change.

9. **Gate check.** If this stage completes a phase, run `/security-gate`
   before declaring the phase done.
