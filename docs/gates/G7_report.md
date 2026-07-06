# Gate G7 Report — Hardening & Demo Readiness

**Date:** 2026-07-06
**Phase:** 7 — Hardening & demo prep (`docs/02_sdlc_plan.md`; `/demo-prep`)
**Result:** PASS for system readiness — two presenter rehearsal items remain
(listed at the end) before the C-level session.

## Verified in this phase (all live)

| Check | Evidence | Result |
|---|---|---|
| Full pipeline **in containers**, incl. AI analysis | Fresh contract via authenticated upload → extract → mask → index → analyze inside compose; lease-v1 detected, planted uncapped-liability found (1 cited finding), `changes_requested`, 6.9 s | PASS |
| LLM-down failure mode | Worker without credentials failed jobs visibly into `failed_analyze`; nothing lost; re-enqueue recovered. **Found & fixed a real bug**: a failing job could overwrite an `approved` document — pipeline now never touches terminal human decisions (audited skip + regression test) | PASS |
| Poor-scan degradation | Family-undetectable docs produce a cited manual-review finding instead of a failed job; OCR-tolerant heading matching shipped (see G5 report) | PASS |
| G5 live numbers for the deck | detection 0.923, 0 uncited, 6.0 s max latency (G5 report) | PASS |
| One-command stack | `docker compose up -d` serves API + React UI on :8000; UI verified; worker consumes jobs with credentials from the read-only `ant` profile mount | PASS |
| Credential handling hardened | Two real integration traps found & fixed: empty-but-set `ANTHROPIC_*` env vars shadow the profile (passthroughs removed); the SDK rejects profile auth over non-loopback cleartext HTTP (containers now use the direct HTTPS API; the host-side proxy remains for local runs) | PASS |

## Demo assets

- `docs/demo_script.md` — 3-act script with talking points, the pii_hold
  centerpiece, rehearsed failure-mode answers, and the measured-numbers table
  (all filled in; sources in `docs/gates/`).
- Users: `reviewer1`/`reviewer2`/`admin1` (`CRS_DEMO_PASSWORD`).
- Corpus currently seeded: 22 golden contracts + 1 live dry-run contract,
  fully processed to `analyzed`/decision states.

## Final metrics table (for the deck — every number measured on our stack)

| Metric | Value | Gate |
|---|---|---|
| Extraction fidelity born-digital / scanned | 1.000 / 0.923 | G2 |
| PII recall (downstream text) | 1.0000 (0/115 leaked) | G3 |
| Novel-PII docs halted (fail-closed) | 6/6 | G3 |
| Hybrid retrieval recall@10 | 1.000 (16 queries) | G4 |
| Known-issue detection | 0.923 (12/13) | G5 |
| Uncited AI findings shown to reviewers | 0 (by construction) | G5 |
| AI analysis latency (max) | 6.9 s in-container | G5/G7 |
| Auto-approvals in the audit trail | 0 (SQL-provable) | G6 |

## Remaining presenter rehearsal items (not system defects)

1. **Scale the corpus to ~100 documents** before the session (bulk upload of
   generated demo contracts through the UI/API; each costs one strong +
   one fast model call — confirm spend before running).
2. **Two clean cold-start rehearsals** of `docs/demo_script.md` end to end
   (`docker compose down && up -d`, seed, run the script twice) on the
   actual demo machine (OQ-5: laptop vs VM still open).

## POC → production reminders (accumulated, for the roadmap slide)

Dev JWT secret & demo passwords → real secrets; ant-profile mount → Secrets
Manager; restricted-schema grants for PII tables; PaddleOCR/Docling for poor
scans; Bedrock provider flip (`CRS_LLM_PROVIDER=bedrock`); real-corpus
validation of all metrics.
