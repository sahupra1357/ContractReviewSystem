# Gate G2 Report — Extraction

**Date:** 2026-07-06
**Phase:** 2 — Extraction (`docs/02_sdlc_plan.md`)
**Result:** PASS (with one measured weakness flagged, below)

## Gate criteria and evidence

| Criterion | Threshold | Measured | Result |
|---|---|---|---|
| Born-digital text fidelity (avg over 16 docs: 12 PDF + 4 DOCX) | ≥ 0.95 | **1.000** (min 1.000) | PASS |
| Scanned text fidelity (avg over 6 docs incl. 2 poor scans) | ≥ 0.90 | **0.923** (min 0.742) | PASS |
| Clause boundaries: expected section headings found (born-digital) | ≥ 0.90 | **1.000** | PASS |

Eval command: `uv run python -m backend.eval.extraction_eval` (golden set @ ae5082b, 22 docs).
Fidelity = SequenceMatcher ratio on whitespace-normalized text vs the generator's canonical source.

## Live end-to-end verification

Uploaded gs-0001 (born-digital PDF), gs-0013 (DOCX), gs-0017 (scanned PDF)
through `POST /ingest/upload` against the compose stack: the containerized
worker claimed the extract jobs, classified each correctly, extracted
(OCR ran inside the container via tesseract), segmented sections, wrote
`<doc-id>/extracted.json` to the **raw** zone, set status `extracted`, and
audited `stage.extracted` with method + section counts.

## What was built

- **Golden set generated** (22 docs, 3 families per OQ-3: lease, purchase,
  vendor-services; deterministic seed): 12 born-digital PDF, 4 DOCX,
  6 scanned (2 poor); 12 docs with planted issues, 10 clean; 6 with novel
  PII; labels + `master_table_seed.yaml` committed and frozen.
- **Classifier**: born-digital vs scanned via PDF text-layer density; DOCX
  and plain text routed to the fast path.
- **Fast path**: pypdf / python-docx extraction with page provenance.
- **Segmenter**: numbered-heading clause segmentation with char offsets and
  page provenance (citation-ready).
- **OCR path**: Tesseract (named in the architecture's OCR layer) via
  pypdfium2 rasterization, CPU-only.
- **Worker**: generic stage runner over the job queue (extract registered;
  mask/index/analyze plug in next), `--once` mode for tests/scripts,
  failures → `failed_extract` + audit, idempotent re-runs.

## Universal checklist (per /security-gate)

- PII isolation: extraction output (still unmasked) written to the **raw**
  bucket only — masked bucket untouched. Enforced by the only storage handle
  the worker holds for artifacts being raw-bucket-scoped.
- Zero auto-approval: no decision paths added.
- Audit completeness: `stage.extracted` / `stage.failed_extract` per document.
- Tests green: 21 passed + invariants; lint clean.
- Docs current: CLAUDE.md updated.

## Measured weakness (flagged, not hidden)

**Poor scans degrade OCR sharply**: the two deliberately degraded scans
scored 0.875 and 0.742 fidelity (blur + noise + rotation). The gate's agreed
metric (scanned average ≥ 0.90) passes, but per-document minima show
Tesseract's limit. Mitigations, in order: (1) documents this poor are rare in
practice; (2) production upgrade path is PaddleOCR/Docling per the design;
(3) Phase 3+ can flag low-confidence extractions for human attention in the
review UI. Carried to the risk register.

## Next

Phase 3 — PII gate: `pii_known_entities` master table (seeded from
`golden_set/master_table_seed.yaml`), deterministic masking (fuzzy,
OCR-tolerant), Presidio fail-closed tripwire → `pii_hold` (Gate G3).
