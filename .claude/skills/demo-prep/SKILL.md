---
name: demo-prep
description: Prepare and verify the C-level demo of the Contract Review Co-Pilot end to end — seeded corpus, live-ingest script, metrics with measured numbers, and failure-mode rehearsal. Use before any stakeholder demo.
---

# C-level demo preparation

The demo's job: prove working functionality and a defensible security story.
Every number shown must be **measured on our own corpus** — no unverified
benchmark claims (this was an explicit caveat in the original security review).

## Step-by-step

1. **Cold-start verification.** From a clean checkout: `docker compose up`
   (or the documented equivalent) must bring up the full stack. Fix anything
   that requires undocumented manual steps — the deck claims one-command
   reproducibility.

2. **Seed the corpus.** Bulk-load the 100-contract corpus; confirm all reach
   `analyzed`/`in_review` with zero stuck jobs. Record total pipeline time.

3. **Script the live path** (the demo's centerpiece):
   1. Drop a new contract into the watched source → show it appear in the queue.
   2. Show the pipeline dashboard advancing (extract → mask → index → analyze).
   3. Open the review brief: risk-ranked findings, click a citation, show the
      masked source passage side-by-side.
   4. Approve with a rationale as a reviewer → show the decision.
   5. Open the audit trail: every step, AI suggestion, and the human decision.
   Target: ingest-to-brief within the minutes SLA, live on stage.

4. **Metrics slide numbers (measured, with the command that produced each):**
   - PII recall/precision on the golden set (must show ≥ 0.98 recall or the
     current measured value with remediation plan).
   - Known-issue detection rate; zero uncited findings.
   - Time-per-review: baseline manual estimate vs with-brief measurement.
   - Cost per contract analyzed; effect of template-diff + caching.
   - Zero auto-approvals — demonstrated from the audit trail itself.

5. **Failure-mode rehearsal.** Exercise and note the graceful behavior for:
   LLM endpoint down (queue holds, no data loss), a bad scan (flagged
   `failed_extract`, visible, retryable), a PII edge case (layered controls
   story). Prepare the honest answer for "what if the AI is wrong?" —
   the human gate, citations, and audit trail.

6. **Security story check.** One slide mapping POC → AWS production
   architecture (design doc §7) + the SOX-aware → SOX-certified roadmap.
   Run `/security-gate` for G7 as the final check.

7. **Dry run twice.** The full script, end to end, twice in a row without
   intervention. Record timings. Only then is the demo "ready".
