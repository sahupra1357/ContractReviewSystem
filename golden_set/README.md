# Golden Set — synthetic labeled evaluation corpus

**Decision basis:** OQ-2 resolution (2026-07-05) — the golden set is fully
**synthetic**: realistic fake contracts with planted fake PII and planted
issues, so labels are known by construction and no real PII is handled during
the POC. Real-contract validation happens at pre-prod.

This corpus is the measuring stick for gates G2–G5 (`docs/02_sdlc_plan.md`)
and for `/self-evaluate` quality checks. **Never** put real contract text or
real PII in this directory.

## Composition target (20–30 documents)

| Slice | Count | Purpose |
|---|---|---|
| Born-digital PDFs (2–3 template families, real-estate flavored: lease, purchase, vendor services) | ~12 | extraction fast path, template-deviation analysis (G2, G5) |
| Scanned/image PDFs incl. deliberately poor scans | ~6 | OCR path quality (G2) |
| DOCX | ~4 | format coverage |
| Contracts with planted **registered** PII (entities present in the seed master table) | all | deterministic masking recall = 1.0 check (G3) |
| Contracts with planted **unregistered/novel** PII (entities NOT in the master table) | ≥6 | proves the fail-closed tripwire halts them in `pii_hold` (G3) |
| Contracts with planted issues (missing clause, unusual liability, off-template terms) | ≥10 | analysis quality — known-issue detection rate (G5) |
| Clean standard contracts (no issues) | ≥5 | false-positive measurement (G5) |

## Layout (one directory per document)

```
golden_set/
  docs/<doc-id>/
    document.pdf|docx        # the synthetic contract
    labels.yaml              # ground truth (schema below)
  master_table_seed.yaml     # entities to register in pii_known_entities for eval runs
```

## labels.yaml schema

```yaml
doc_id: gs-0001
family: lease-v1            # template family, or "none"
format: born-digital-pdf    # born-digital-pdf | scanned-pdf | docx
pii:                        # EVERY planted PII entity, exhaustively
  - text: "Jordan Rivera"
    type: PERSON
    registered: true        # true = in master_table_seed.yaml; false = novel (must trigger pii_hold)
    locations: [{page: 1, occurrences: 3}]
key_terms:
  parties: ["Acme Property LLC", "Jordan Rivera"]
  effective_date: "2026-03-01"
  term_months: 24
  monthly_amount: "USD 4,200"
  renewal: "auto-renew 12 months unless 60-day notice"
known_issues:               # what the AI analysis MUST find (G5)
  - id: iss-1
    clause_ref: "§8.2"
    description: "Uncapped liability — deviates from lease-v1 template cap"
    severity: high
expected_clean: false       # true for no-issue control documents
```

## Rules

1. Labels are exhaustive: an unlabeled PII entity in a document is a bug in
   the golden set, not a pipeline win.
2. Every eval run records the golden-set git revision and the master-table
   version, so numbers are reproducible.
3. Documents are generated + hand-verified once, then **frozen**; changes
   require a new doc-id (never silently edit a labeled document).
4. The generation scripts live in `golden_set/generator/` (built in Phase 2)
   and must be deterministic (seeded) so the corpus can be regenerated.

## Metrics computed from this corpus

- **G2:** text fidelity (born-digital ≥95%, scans ≥90%); clause-boundary spot-check.
- **G3:** PII recall ≥ 0.98 on downstream-reaching text (post-hold-resolution);
  zero unregistered planted entities pass unhalted; tripwire false-alarm rate.
- **G4:** retrieval recall@10 on labeled query→clause pairs.
- **G5:** known-issue detection rate; zero uncited findings; clean-contract
  false-positive rate; per-contract latency vs the minutes SLA.
