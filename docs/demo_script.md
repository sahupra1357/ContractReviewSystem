# C-Level Demo Script — Contract Review Co-Pilot

**Duration:** ~12 minutes. **Environment:** one laptop, `docker compose up -d`.
Rehearse twice per `/demo-prep` before presenting (Gate G7).

## Pre-demo checklist (30 min before)

```bash
docker compose up -d                       # full stack on :8000
# LLM credentials for the analyze stage (host proxy or key must be live):
#   ant auth login   (once)   → export ANTHROPIC_AUTH_TOKEN=$(ant auth print-credentials --access-token)
#   docker compose up -d worker backend    # restart to pick up env
cd backend
export CRS_DATABASE_URL=postgresql+psycopg://crs:crs@localhost:5433/crs
uv run python -m backend.pii.seed ../golden_set/master_table_seed.yaml
uv run python -m backend.seed_users        # reviewer1 / reviewer2 / admin1
```
Open http://localhost:8000 — sign in as `reviewer1`. Confirm the dashboard
shows the seeded corpus fully processed and the queue is populated.

## Act 1 — The security story (3 min, slides + dashboard)

Talking points, each backed by a measured number (docs/gates/):
- "Every stage runs in our environment; contracts never leave it." (design §7 AWS mapping)
- "PII is masked **before** anything reaches an index or a model — measured
  recall 1.0000 on our labeled corpus, and the system **fail-closed halts**
  any document with a possible unregistered entity: 6 of 6 novel-PII test
  documents were stopped." (G3)
- "Nothing is ever auto-approved. Watch the audit trail prove it."

## Act 2 — Live ingest to review brief (5 min, the centerpiece)

1. **Upload** (as reviewer1): drag 2–3 fresh contracts incl. one duplicate →
   show per-file results: accepted vs "duplicate — skipped" (dedup live).
2. **Dashboard**: watch statuses advance ingested → extracted → masked →
   indexed → analyzed within the minutes SLA.
3. **PII gate moment** (upload the prepared novel-counterparty contract):
   it halts in `pii_hold`. Switch to admin1 → PII Admin → show the flagged
   span → "Add to master" → document resumes automatically. *"Unknown PII
   never flows through — a person decides, and it's audited."*
4. **Open the contract** from the queue: masked text left, AI review brief
   right — risk-ranked findings; click a citation → the exact clause
   highlights. Key terms table. *"The reviewer verifies instead of reads."*

## Act 3 — Human decision + audit (3 min)

1. Type a rationale (buttons stay disabled until it's entered), Approve.
2. Open the Audit tab: the full chain — every pipeline stage (system) and
   the human decision with rationale (reviewer1). *"Defensible end to end."*
3. Show the RBAC guard live if asked: sign in as admin1 → decision buttons
   are absent (admin cannot decide; reviewer cannot administer PII).

## Metrics slide (measured on our corpus — sources in docs/gates/)

| Claim | Number | Source |
|---|---|---|
| Extraction fidelity (born-digital / scanned) | 1.000 / 0.923 | G2 |
| PII recall on downstream text | 1.0000 (0/115 leaked) | G3 |
| Novel-PII documents halted | 6/6 (fail-closed) | G3 |
| Tripwire false-alarm burden | 0% clean docs held; both poor scans held & resolved | G3/G4 |
| Retrieval recall@10 | 1.000 (16 labeled queries) | G4 |
| Known-issue detection / analysis latency | run `analysis_eval` → fill in | G5 |
| Auto-approvals in audit trail | 0 (provable by query) | G6 |

Honest caveats to volunteer (they build credibility): metrics are measured on
the synthetic labeled corpus — real-contract validation is the pre-prod step;
the reranker's industry "+40%" claim is unvalidated on our data and not ours
to quote.

## Failure-mode answers (rehearsed)

- **"What if the AI is wrong?"** Findings must cite the source clause or be
  discarded automatically; the reviewer sees the evidence; nothing is
  approved without a human rationale.
- **"What if the model is down?"** Documents queue in `failed_analyze`,
  visible on the dashboard, nothing lost; re-enqueue after recovery. (Drilled
  live in Phase 7 — and the drill caught & fixed a real bug: pipeline
  failures can never overwrite a human decision.)
- **"What about a brand-new counterparty?"** That's the pii_hold demo in
  Act 2 — the system stops rather than guesses.
