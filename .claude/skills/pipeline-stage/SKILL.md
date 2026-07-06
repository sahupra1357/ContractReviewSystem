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

5. **Tests before done:**
   - Unit tests for the stage logic.
   - Integration test: document enters in the prior status, leaves in the
     next status, audit rows exist, re-run is idempotent.
   - If the stage affects extraction/PII/retrieval/analysis quality, run the
     golden-set eval and compare to the previous baseline — regressions block.

6. **Update docs.** If the stage's behavior deviates from design doc §3 in any
   confirmed way, update the design doc in the same change.

7. **Gate check.** If this stage completes a phase, run `/security-gate`
   before declaring the phase done.
