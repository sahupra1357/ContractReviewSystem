---
name: unit-tests
description: Write and run unit/integration tests for the Contract Review Co-Pilot — pytest for the Python backend, Vitest for the React frontend — including the invariant tests every pipeline stage and API change must carry. Use whenever writing tests, adding a feature that needs tests, or when coverage of a stage is in question.
---

# Unit testing standards

Testing here has two jobs: ordinary correctness, and **proving the security
invariants hold** (design doc §2). A feature without its invariant tests is
not done, even if it works.

## Ground rules

- Tests live next to the code they test: `backend/**/tests/` (pytest),
  `frontend/src/**/*.test.tsx` (Vitest + React Testing Library).
- Run with `uv run pytest` (backend) and `npm test` (frontend). If these
  commands don't exist yet (pre-Phase 0), set them up first and record them
  in CLAUDE.md's Commands section.
- **Never use real contract text or real PII in fixtures.** Fixtures are
  synthetic documents with planted, labeled fake PII (fake names, fake
  account numbers). Keep them in `backend/tests/fixtures/`.
- No network in unit tests: LLM calls go through the Bedrock-shaped adapter —
  substitute a fake adapter returning canned, citation-bearing responses.
  Presidio/OCR get service fakes in unit tests; real containers only in
  integration tests.
- Determinism: no sleeps, no time-dependent assertions; freeze time where
  timestamps matter (audit events).

## What every change type must test

**Pipeline stage** (also see `/pipeline-stage`):
- Happy path: document enters in prior status, leaves in next status.
- Idempotency: running the same job twice produces no duplicate
  chunks/embeddings/entities (assert row counts).
- Failure path: a poisoned input lands in `failed_<stage>` with the error
  recorded and an audit event written — never silently skipped.
- Audit: assert the exact audit rows (actor=system, action, object).

**Invariant tests (the non-negotiables — keep these in a dedicated
`tests/invariants/` suite that runs on every CI build):**
- PII gate: the DB role / bucket client used by index & analyze stages gets a
  permission error when reading the raw store (test the grant, not the code).
- Zero auto-approve: the workflow state machine rejects any programmatic
  transition to `approved`/`rejected`; only the human-decision service
  function accepts it, and only with an authenticated user + non-empty rationale.
- Audit append-only: UPDATE and DELETE on `audit_events` fail at the DB level.

**API endpoint:**
- AuthZ: non-reviewer → 403 on decision endpoints; unauthenticated → 401.
- Validation: decision without rationale → 4xx.
- Audit row asserted for every mutating call.

**Frontend component:**
- Queue ordering renders per triage priority; citation click focuses the
  correct source passage; approve/reject buttons disabled without rationale.

## Quality vs. quantity

- Assert behavior and outputs, not implementation details or mock call counts.
- One clear failure mode per test; name tests after the behavior
  (`test_duplicate_document_is_skipped_and_audited`).
- Don't chase coverage numbers; chase the failure scenarios listed above.
  If a test can't fail for a real reason, delete it.

## Relationship to the golden-set eval

Unit tests prove code correctness; the golden-set eval harness
(extraction accuracy, PII recall, retrieval quality, groundedness) proves
**model/pipeline quality** — see `/self-evaluate`. Quality gates (G2–G5) are
eval results, not unit-test results. Both must pass; neither substitutes for
the other.
