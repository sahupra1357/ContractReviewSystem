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
| `crs-worker` | worker (Docker, pro ~8GB) | pipeline incl. BGE-M3 inference; 10GB disk caches model weights |
| `crs-postgres` | managed Postgres 16 | pgvector enabled by migration 0004 |
| `crs-minio` | private service + 10GB disk | raw/masked/audit zones (buckets auto-created by the app) |
| `crs-presidio-analyzer` / `-anonymizer` | private services | the PII tripwire |

Monthly cost is dominated by the worker's RAM plan — review Render pricing
before deploying; scale the worker down (or suspend it) between demo sessions.

## Deploy steps

1. Push the repo to GitHub and click **New → Blueprint** in Render, pointing
   at the repo (it reads `render.yaml`).
2. When prompted, set the two `sync: false` secrets:
   - `ANTHROPIC_API_KEY` — a real API key (the local `ant` OAuth profile does
     not exist on Render). Scope a dedicated key for the demo; revoke after.
   - `CRS_DEMO_PASSWORD` — login password for `reviewer1`/`reviewer2`/`admin1`.
3. First build takes a while (torch layer); the worker's first analyze also
   downloads BGE-M3 (~2.3GB) into its disk-backed cache.
4. **Verify internal hostnames** (one-time): open each private service in the
   dashboard and confirm its internal address matches the URLs in the
   blueprint env vars (`crs-minio:9000`, `crs-presidio-analyzer:3000`,
   `crs-presidio-anonymizer:3000`); correct the env vars if Render assigned
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

## Teardown

Delete the Blueprint's services and the database after the demo, and revoke
the demo API key. Nothing in this deployment is meant to outlive the demo.
