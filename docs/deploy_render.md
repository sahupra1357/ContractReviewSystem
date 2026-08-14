# Render Demo Deployment — SYNTHETIC DATA ONLY

**Policy first:** this deployment exists to give the C-level demo a shareable
URL. It runs the **synthetic corpus only** — never upload a real contract to
a PaaS-hosted instance. The production target remains the in-VPC AWS build
(design doc §7); state this explicitly in the demo ("this URL is throwaway
demo infrastructure; the real system runs inside our VPC").

## What gets deployed (from `render.yaml`)

| Service | Type / plan | Purpose |
|---|---|---|
| `crs-backend` | web (Docker, standard) | FastAPI + React UI, migrations on boot |
| `crs-worker` | worker (Docker, standard) | pipeline; hosted embeddings, so no local model and no disk |
| `crs-postgres` | managed Postgres 16 | pgvector enabled by migration 0004 |
| `crs-minio` | private service + 10GB disk | raw/masked/audit zones (buckets auto-created by the app) |
| `crs-presidio-analyzer` | private service | the PII tripwire |

**Embeddings are hosted** here (`CRS_EMBEDDING_PROVIDER=openai`, 2026-08-13),
not the design's self-hosted BGE-M3. That removes torch from the image
(8.66GB → ~697MB), removes the worker's model-weight disk, and drops its plan
from `pro` to `standard`. The cost: masked text goes to a third party, and the
**G4/G5 gate numbers were measured on BGE-M3, so they do not describe this
deployment** — re-run the evals or present them as reference-stack figures.
Reverting is four keys and a disk — see the comments in `render.yaml`.

Review Render pricing before deploying, and suspend the services between demo
sessions.

## Deploy steps

1. Push the repo to GitHub and click **New → Blueprint** in Render, pointing
   at the repo (it reads `render.yaml`).
2. When prompted, set the three `sync: false` secrets:
   - `ANTHROPIC_API_KEY` — a real API key (the local `ant` OAuth profile does
     not exist on Render). Scope a dedicated key for the demo; revoke after.
   - `CRS_EMBEDDING_API_KEY` — an OpenAI key, used by the index stage only.
   - `CRS_DEMO_PASSWORD` — login password for `reviewer1`/`reviewer2`/`admin1`.
3. The build is quick now that torch is gone, and **no model weights are
   downloaded at runtime** — the index stage calls the embeddings API and
   analyze was always just an LLM call. (Switching back to
   `CRS_EMBEDDING_PROVIDER=bge-m3` restores both the slow torch build and a
   ~2.3GB download on the worker's first index job, which is what the
   `hf-cache` disk existed for.)
4. **Verify internal hostnames** (one-time): open each private service in the
   dashboard and confirm its internal address matches the URLs in the
   blueprint env vars (`crs-minio:9000`, `crs-presidio-analyzer:3000`,
   ); correct the env vars if Render assigned
   different names/ports, then redeploy.
5. Seed the demo: dashboard → `crs-backend` → **Shell** →
   ```bash
   python -m backend.seed_demo
   ```
   (idempotent: users, PII master table, 22 synthetic contracts). Watch the
   dashboard page in the app as the worker processes them; the novel-PII
   docs will halt in `pii_hold` — resolving them in PII Admin *is* the demo.

## Differences vs the local compose stack

- LLM credentials: `ANTHROPIC_API_KEY` env (no profile mount, no local proxy).
- Buckets are auto-created by the storage layer (no minio-init container).
- `CRS_DATABASE_URL` arrives as `postgres://…` and is normalized in `db.py`.
- JWT secret and MinIO credentials are Render-generated, not dev defaults.
- Embeddings are hosted (`openai`), not local BGE-M3 — compose still defaults to
  `bge-m3`, so vectors indexed here and locally are **not** interchangeable.
  They are partitioned by `model_name`, so nothing silently mixes; a provider
  switch means re-indexing.

## Teardown

Delete the Blueprint's services and the database after the demo, and revoke
the demo API key. Nothing in this deployment is meant to outlive the demo.
