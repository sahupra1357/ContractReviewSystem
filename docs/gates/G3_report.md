# Gate G3 Report — PII Gate (HARD GATE)

**Date:** 2026-07-06
**Phase:** 3 — PII gate (`docs/02_sdlc_plan.md`; design doc §3.3
deterministic-primary, fail-closed)
**Result:** PASS

## Gate criteria and evidence

| Criterion | Threshold | Measured | Result |
|---|---|---|---|
| PII recall on downstream-reaching text (post-hold-resolution) | ≥ 0.98 | **1.0000** (0 of 115 labeled entities leaked) | PASS |
| Unregistered planted entities passing unhalted | 0 | **0** — all 6 novel-PII docs halted, incl. both poor scans | PASS |
| Tripwire false-alarm rate (hold burden, info) | reported | **0/16 non-novel docs (0%)** | reported |

Eval command: `uv run python -m backend.eval.pii_eval` (22 golden docs,
115 labeled PII entities, live Presidio analyzer).

## Live end-to-end verification (compose stack)

1. Master table seeded (12 registered entities, each insert audited).
2. Clean doc (gs-0002) uploaded → extract → mask → **`masked`**, artifact in
   the masked bucket with `[ORG-n]`/`[PERSON-n]` placeholders.
3. Novel-PII doc (gs-0007) uploaded → **`pii_hold`** with 4 flags: person
   (Presidio, incl. a line-broken OCR-style variant), street address and
   account number (custom regex recognizers). **Nothing written to the
   masked zone.**
4. Human resolution via API: 1 dismissal (rationale required + recorded),
   3 add-to-master (audited `pii_master.added`); last resolution
   auto-requeued masking; re-run → **`masked`**; artifact verified free of
   all novel entities.
5. Full audit chain present: `stage.pii_hold` → `pii_hold.added_to_master` /
   `pii_hold.dismissed` (human, with rationale) → `stage.mask_requeued` →
   `stage.masked`.

## What was built

- Migration 0003: `pii_known_entities` (master table), `pii_entity_map`
  (layer-tagged), `pii_holds`.
- **Layer 1 masker**: fuzzy/OCR-tolerant matching (flexible separators,
  strict token content), stable per-document placeholders, longest-entity
  precedence, entity map recording.
- **Layer 2 tripwire** (detector only, never masks): Presidio with
  PII-relevant types + score threshold, custom regex recognizers
  (org-suffix names, street addresses incl. ", City, ST" tails, account
  numbers) — added because the G0 smoke test showed Presidio missing
  account patterns. Dismissed spans suppressed on re-run.
- Mask worker stage chained after extract; hold-resolution + master-table
  API; seed script.
- 15 new unit tests (36 total passing + invariants).

## Universal checklist (per /security-gate)

- PII isolation: masked artifacts written only via `MaskedStorage`; raw and
  masked zones are separate buckets and separate storage handles; unit test
  asserts a held document leaves the masked zone empty.
- Zero auto-approval: hold resolution requires an authenticated actor;
  dismissal requires a rationale (422 otherwise) — no automatic release path.
- Audit completeness: every mask outcome, master-table change, and hold
  resolution audited with actor + rationale.
- Tests green: 36 passed + invariant suite. Lint clean.

## Honest caveats (for the demo deck)

1. **Perfect scores are a property of the synthetic corpus** — registered
   entities render cleanly and novel entities have detector-friendly shapes.
   Real-corpus validation at pre-prod is the required next proof; the
   architecture (fail-closed) is what makes imperfect detection safe.
2. Restricted-schema separation for `pii_entity_map`/`pii_known_entities`
   (separate DB grants) is documented but not enforced in the single-role
   POC database — Phase 6/hardening item.
3. OCR-garbled registered entities beyond separator mutations (e.g. `0`→`O`
   character swaps) would evade the fuzzy masker; the Presidio tripwire and
   the human review gate are the designed backstops. Not observed on the
   golden set.

## Next

Phase 4 — Knowledge & index: clause chunking from masked artifacts,
embeddings + chunk-hash cache, hybrid retrieval (pgvector + FTS + RRF),
graph-lite entities/relationships (Gate G4).
