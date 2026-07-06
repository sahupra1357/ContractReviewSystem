---
name: self-evaluate
description: Agent self-evaluation loop to run while coding and before declaring any task done — verify the change actually works end-to-end, check it against the design doc and security invariants, run the golden-set eval when quality is affected, and report results honestly. Use after implementing any feature, fix, or refactor in this project.
---

# Self-evaluation while coding

Purpose: catch your own errors before the user or a gate does. Run this loop
**during** implementation (steps 1–3 at each meaningful checkpoint) and in
full before saying "done". Never report success you haven't observed.

## The loop

### 1. Spec check — am I building what was decided?
- Re-read the relevant section of `docs/03_design_document.md` and the
  CLAUDE.md Decision Log. List each requirement the change touches and where
  your code satisfies it.
- If your implementation deviates from the design, or the design is silent on
  something you need: **STOP** — present evidence + a suggestion to the
  product owner and get confirmation (standing rule: DO NOT ASSUME). Do not
  pick a direction silently, even a reasonable one.

### 2. Invariant check — did I break a non-negotiable?
Walk the three invariants explicitly against your diff:
- Does any code downstream of the PII gate touch raw text or the raw store?
- Did I introduce any path that sets `approved`/`rejected` outside the
  human-decision API?
- Does every new action/stage-transition write an audit event? Any grant or
  migration weakening append-only audit?
If any answer is bad or unclear, fix it before proceeding — these override
feature completeness.

### 3. Execution check — does it actually run?
- Run the affected code for real, not just the type checker: the specific
  tests (`uv run pytest <path>`), and where the change has a runtime surface,
  drive it — process a fixture document through the stage, hit the endpoint,
  load the UI view. "It compiles" and "tests I didn't run probably pass" are
  not evidence.
- Confirm idempotency for pipeline work by running it twice.

### 4. Quality check — did I move the measured numbers?
If the change can affect extraction, PII masking, retrieval, or analysis
output: run the golden-set eval harness and compare to the recorded baseline.
- Improvement or neutral → record the new numbers alongside the change.
- Regression → the change is not done; investigate or escalate with the
  numbers. Never re-baseline downward to make a regression disappear.
- (Pre-Phase-2, before the harness exists: note explicitly that quality was
  not measured, so the gap is visible.)

### 5. Test-adequacy check
Ask: "what input would make this change fail, and does a test exert it?"
Add missing tests per `/unit-tests` — especially failure paths and the
invariant suite for anything security-adjacent.

### 6. Honest report
When reporting done, state — with the command/output that proves each:
- What was verified by running it (tests run + results, eval numbers if run).
- What was NOT verified and why (e.g., "OCR path untested on GPU — none
  available locally", "eval harness not yet built").
- Any deviation confirmed with the product owner, now recorded in the
  Decision Log.
Failed tests, skipped steps, and unmeasured quality are reported as exactly
that — never rounded up to "works".

## When the loop fails repeatedly

If you cycle on the same failure 3+ times, stop patching. Re-read the design
doc section, write down the mismatch between expectation and observation, and
present it to the user with evidence and 1–2 options rather than burning
further attempts.
