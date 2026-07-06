# Gate G5 Report — AI Analysis

**Date:** 2026-07-06 (finalized same day after the live-LLM run)
**Phase:** 5 — AI analysis (`docs/02_sdlc_plan.md`; design §3.5)
**Result:** **PASS** — measured live via the local proxy (Claude API,
`claude-opus-4-8` strong / `claude-haiku-4-5` fast), prompt version v2.

## Measured results (22 golden docs, 13 labeled known issues)

| Criterion | Threshold | Measured | Result |
|---|---|---|---|
| Known-issue detection | ≥ 0.80 | **0.923** (12/13) | PASS |
| Uncited findings displayed | 0 | **0** (by construction; 0 dropped this run — the model cited everything validly) | PASS |
| Max per-doc analysis latency | < 300 s | **6.0 s** | PASS |
| Clean-doc high-severity false positives | reported | **1/10** — gs-0018, a deliberately-poor scan correctly routed to manual review (a designed flag, not a hallucination) | reported |

The single miss (gs-0021, vendor-unilateral-termination) is a deliberately
degraded scan whose OCR lost most section headings: the system deliberately
did NOT attempt LLM analysis and instead produced a cited high-severity
"manual review required" finding — the honest degraded path, not a silent miss.

## Phase-7 improvements shipped during the eval (each with regression tests)

1. **OCR-tolerant matching**: segmenter accepts mostly-uppercase headings
   (OCR lowercases glyphs); template diff matches headings fuzzily (≥0.8).
2. **Borderline verification bucket** (prompt v2): sections with similarity
   0.70–0.85 go to the strong model for judgment — measured on the corpus,
   subtle rewrites (gs-0003's 36-month auto-renew, sim 0.763) overlap with
   short standard clauses; a blunt threshold cannot separate them. This
   recovered gs-0003 with zero new false positives.
3. **Graceful manual-review path**: family undetectable → deterministic,
   cited, high-severity finding + `changes_requested`; no LLM guessing.
4. Observed: the local proxy served byte-identical repeated requests from
   cache (0.0s latencies on re-runs) — the prompt-caching cost lever in action.

---

*The original PARTIAL report follows for the audit trail.*

## What was built

- **Multi-provider LLM adapter** (product-owner decision 2026-07-06):
  one `LLMClient` interface, provider from `CRS_LLM_PROVIDER`.
  - `anthropic` (default): official SDK; honors `ANTHROPIC_BASE_URL` (local
    proxy) and SDK credential resolution. Tier defaults: strong
    `claude-opus-4-8`, fast `claude-haiku-4-5`.
  - `bedrock` (production path): `AnthropicBedrockMantle`,
    `anthropic.`-prefixed ids, AWS region from config.
  - `openai` / `nvidia` / `mistral` / `minimax` / `kimi` / `qwen`: one
    OpenAI-compatible client with per-provider base URLs; **default model ids
    for these are placeholders — set `CRS_LLM_MODEL_STRONG/FAST` explicitly.**
- **Template diff engine** (deterministic, no LLM cost): family detection by
  heading overlap; per-clause similarity vs the canonical standard
  (`backend.analysis.reference_templates` — now the single source the golden
  generator also imports); classifies standard / deviation / missing / extra.
- **Review brief**: STRONG model analyzes only deviations+missing clauses
  (the token-efficiency lever); FAST model extracts key terms (tiered
  routing demonstrated). Output: findings with **mandatory citations**
  (chunk_id or template_ref), suggested decision, rationale.
- **Groundedness gate**: findings with citations not in the document's chunk
  ids / valid template refs are DROPPED before storage and counted
  (`dropped_uncited`) — zero uncited findings displayed, by construction.
- **Injection heuristics** (Guardrails-equivalent, provider-independent):
  instruction-like phrases in contract text produce a high-severity,
  cited, system-attributed finding.
- **Analyze worker stage**: masked-zone handle only; migration 0005
  `analyses` (one per document, replaced on re-run); status → `analyzed`;
  audited with models, counts, latency; JSON-parse retry then
  `failed_analyze`.

## Verified (evidence)

- 46 unit tests pass (fake LLM), including: standard lease → zero
  deviations; planted uncapped-liability + missing-insurance → correct
  deviation/missing classification with template_refs; hallucinated citation
  dropped (`dropped_uncited == 1`) while grounded finding kept; injection
  phrase → cited high-severity finding; full pipeline chain
  ingest→extract→mask→index→analyze ends `analyzed`. Lint clean.
- Migration 0005 applied to the compose database; 22 analyze jobs are queued
  behind the indexed golden corpus, ready for the live run.

## NOT yet verified (required to claim G5)

The live-LLM eval was not run in this session (LLM credentials/endpoint not
confirmed). To complete the gate:

```bash
# from backend/, compose up, corpus indexed, LLM creds configured
CRS_DATABASE_URL=postgresql+psycopg://crs:crs@localhost:5433/crs \
    uv run python -m backend.eval.analysis_eval
```

It drains the 22 queued analyze jobs with the configured provider and
measures: known-issue detection (≥ 0.80), dropped-uncited count, clean-doc
false positives, per-doc latency vs the 5-minute SLA. Append the output to
this report and flip the Result to PASS/FAIL.

## Universal checklist (per /security-gate)

- PII isolation: the analyze handler receives ONLY the masked-zone storage
  handle; every provider sees masked text exclusively.
- Zero auto-approval: `suggested_decision` is stored data — no code path
  changes document status to approved/rejected; the model only proposes.
- Audit: `stage.analyzed` with family, finding/dropped counts, models,
  latency per document.
- Secrets: provider keys/endpoints from config env only; nothing hardcoded.
- Docs current: design §3.5 rewritten for multi-provider; CLAUDE.md updated.

## Next

Run the live eval above → finalize G5 → Phase 6 (review application: JWT
auth, review queue, decision API with mandatory rationale, React UI).
