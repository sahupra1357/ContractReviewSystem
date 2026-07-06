---
name: security-gate
description: Run the phase-gate checklist (G0–G7) before declaring an SDLC phase complete. Use at the end of every phase, before demos, and whenever the user asks to verify security posture or gate readiness.
---

# Phase gate check

Gates are defined in `docs/02_sdlc_plan.md`. A phase is not done until its
gate passes and the result is recorded. Never soften a gate to pass it — if a
gate cannot be met, report the measured result with evidence and options to
the product owner.

## Procedure

1. **Identify the gate.** Match current work to G0–G7 in the SDLC plan and
   restate its pass criteria verbatim.

2. **Run the universal checklist (every gate):**
   - [ ] PII isolation: downstream stages/roles cannot read raw text — verify
     grants/bucket policy, not just code review.
   - [ ] Zero auto-approval: grep/inspect for any programmatic transition to
     `approved`/`rejected`; only the human-decision API path may exist.
   - [ ] Audit completeness: for a sample document, every stage transition and
     action of this phase appears in `audit_events`; table remains INSERT-only.
   - [ ] Secrets: no credentials/endpoints hardcoded or committed; config only.
   - [ ] Tests green: unit + integration for everything the phase added.
   - [ ] Docs current: design doc and CLAUDE.md reflect what was actually built.

3. **Run the gate-specific criteria.** Notable hard ones:
   - **G3 (PII):** measured recall ≥ 0.98 on the labeled golden set — run the
     eval harness, record the number, precision, and confusion cases.
   - **G5 (Analysis):** zero uncited findings on golden-set contracts;
     known-issue detection rate vs the agreed threshold; latency within the
     minutes SLA.
   - **G6 (App):** RBAC probe — a non-reviewer identity must receive 403 on
     the decision endpoint; decision without rationale must be rejected.

4. **Evidence, not assertion.** Each checked item cites how it was verified
   (command run, test name, measured number). "Looks fine" does not pass.

5. **Record the outcome.** Write a short gate report to
   `docs/gates/G<N>_report.md`: date, criteria, evidence, PASS/FAIL, and any
   product-owner decisions taken. Link it from the Decision Log if a decision
   was made.

6. **On FAIL:** do not proceed to the next phase. Present the failing
   evidence and remediation options to the product owner.
