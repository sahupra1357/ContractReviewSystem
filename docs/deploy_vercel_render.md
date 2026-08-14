# Free-Tier Demo Deployment — Vercel + Render + R2 + Modal

**SYNTHETIC DATA ONLY.** This deployment puts raw contract text in third-party
storage and sends masked text to a third-party serverless host. It exists to
give the demo a shareable URL. Never upload a real contract to it. The
production target is the in-VPC AWS build (design doc §7), and the faithful
managed deployment is `render.yaml`.

---

## Why this is not just "deploy render.yaml"

Render's free tier has **no worker tier, no private services, and no disks**
([docs](https://render.com/docs/free)), which is four of the six services in
`render.yaml`. Rather than deleting them, each is relocated behind a config
flag whose default is the original:

| `render.yaml` service | Free-tier home | Flag | Default |
|---|---|---|---|
| `crs-worker` | thread in the API process | `CRS_INLINE_WORKER=1` | `0` (real worker) |
| `crs-minio` | Cloudflare R2 | `CRS_S3_*` | MinIO |
| `crs-presidio-analyzer` | Modal | `CRS_PRESIDIO_ANALYZER_URL` | compose service |
| BGE-M3 embeddings | OpenAI `text-embedding-3-small` | `CRS_EMBEDDING_PROVIDER=openai` | `bge-m3` |

Nothing was removed. `docker compose up -d` and `render.yaml` behave exactly as
before, and the full-cloud rollout restores every original component by simply
not setting these flags.

Two supporting facts that make the swaps cheap:

- **The anonymizer was dead code and has been deleted** (2026-08-14). Nothing
  ever called it — the master table does all masking.
- **1024 dimensions.** `EMBEDDING_DIM = 1024` and `text-embedding-3-*` accept a
  `dimensions` argument, so the OpenAI adapter asks for 1024 and the existing
  pgvector column is unchanged — **no migration**. `model_name` is
  provider-qualified (`openai:text-embedding-3-small`), and since it keys both
  the embedding cache (`knowledge/service.py:52`) and the dense-search filter
  (`knowledge/retrieval.py:79`), BGE-M3 and OpenAI vectors can never be
  compared against each other.

### What you give up

- **Retrieval/analysis metrics no longer hold.** G4 (recall@10 = 1.000) and G5
  (detection 0.923) were measured with BGE-M3. Re-run the evals or present them
  as "measured on the reference stack", not on this URL.
- **The service sleeps.** Free web services spin down after 15 idle minutes and
  take ~1 min to wake. The in-process pipeline sleeps with it. **Hit the URL a
  few minutes before any demo.**
- **The database expires 30 days after creation.** Free Postgres is deleted;
  diary that date.
- Free Postgres is limited to one per workspace, 1 GB.

---

## Prerequisites

Accounts: GitHub, Render, Vercel, Cloudflare, Modal, plus an OpenAI API key
(embeddings) and an Anthropic API key (analysis). Locally you need `npm`, and
`pip install modal` for step 2.

---

## Step 1 — Cloudflare R2 (object store)

1. Cloudflare dashboard → **R2** → **Create bucket**. Make three:
   `raw`, `masked`, `audit`.
   Pre-creating matters: `storage.py` will try to create them on first use,
   which needs a token with bucket-create rights.
2. **R2 → Manage API Tokens → Create API Token**, permission **Object Read &
   Write**, scoped to those buckets. Save the **Access Key ID** and **Secret
   Access Key** (shown once).
3. Note your **endpoint**: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

You'll set `CRS_S3_ENDPOINT_URL`, `CRS_S3_ACCESS_KEY`, `CRS_S3_SECRET_KEY`, and
`CRS_S3_REGION=auto` in step 4. R2 requires the literal string `auto`.

## Step 2 — Modal (PII tripwire)

The tripwire is what makes the PII gate fail closed on unregistered entities —
it is not optional. It needs ~2 GB for spaCy, so it moves off the web host
rather than being switched off.

```bash
pip install modal
modal setup                                   # opens a browser to authenticate
modal deploy deploy/modal_presidio.py
```

Modal prints a URL like
`https://<workspace>--crs-presidio-analyzer-web.modal.run`.

The endpoint is deployed with `requires_proxy_auth=True`, so create a token at
**Modal dashboard → Settings → Proxy Auth Tokens** and verify with it:

```bash
curl -X POST https://<your-modal-url>/analyze \
  -H 'Content-Type: application/json' \
  -H 'Modal-Key: wk-...' -H 'Modal-Secret: ws-...' \
  -d '{"text":"Contact Gregory Alvarado at greg@example.com","language":"en"}'
```

You should get a JSON array containing `PERSON` and `EMAIL_ADDRESS`. Without the
headers you should get a 401 — if an unauthenticated call succeeds, proxy auth
did not take effect and anyone with the URL can spend your Modal credits.

The first call after idle takes ~10–30s (cold start loading spaCy) — within the
tripwire's 60s timeout, but expect one slow document.

The backend needs all three values (`CRS_PRESIDIO_ANALYZER_URL`,
`CRS_PRESIDIO_AUTH_KEY`, `CRS_PRESIDIO_AUTH_SECRET`); both credential halves are
required or the tripwire sends no headers at all and every call 401s.

> Modal web endpoints are **public by default**. For anything beyond a throwaway
> demo, add proxy auth.

## Step 3 — Render Postgres

Dashboard → **New → Postgres**. Name `crs-postgres`, **PostgreSQL 16**, plan
**Free**. Copy the **Internal Database URL**.

pgvector is [supported](https://render.com/docs/postgresql-extensions) and
migration 0004 runs `CREATE EXTENSION vector` for you on first boot.

## Step 4 — Render web service (API + pipeline)

Dashboard → **New → Web Service** → connect the repo.

| Setting | Value |
|---|---|
| Language / Runtime | **Docker** |
| Dockerfile path | `backend/Dockerfile` |
| Docker build context | `.` (repo root — the UI is built into the image) |
| Instance type | **Free** |
| Health check path | `/health` |

Then add environment variables. Render exposes them as Docker build args, which
is how `CRS_EXTRAS` reaches the Dockerfile's `ARG`:

```bash
CRS_EXTRAS=openai                    # skips torch: 8.66GB image -> 697MB
CRS_DATABASE_URL=<Internal Database URL from step 3>
CRS_INLINE_WORKER=1                  # pipeline runs in-process (no worker tier)

CRS_S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CRS_S3_ACCESS_KEY=<R2 access key>
CRS_S3_SECRET_KEY=<R2 secret key>
CRS_S3_REGION=auto
AWS_REQUEST_CHECKSUM_CALCULATION=when_required   # see troubleshooting

CRS_PRESIDIO_ANALYZER_URL=https://<your-modal-url>
CRS_PRESIDIO_AUTH_KEY=wk-...
CRS_PRESIDIO_AUTH_SECRET=ws-...

CRS_EMBEDDING_PROVIDER=openai
CRS_EMBEDDING_MODEL=text-embedding-3-small
CRS_EMBEDDING_API_KEY=<OpenAI key>

ANTHROPIC_API_KEY=<Anthropic key>    # analysis stage
CRS_JWT_SECRET=<long random string>
CRS_DEMO_PASSWORD=<demo login password>
CRS_ENVIRONMENT=render-free
```

Deploy. Migrations run automatically on boot (`alembic upgrade head` is the
container command, and a failing migration fails the deploy). Confirm:

```bash
curl https://<your-service>.onrender.com/health
# {"status":"ok","environment":"render-free"}
```

`render.free.yaml` in the repo root captures all of the above if you prefer a
Blueprint — Render only reads a file named `render.yaml`, so rename it on a
deploy branch. With just two services, the dashboard route above is simpler.

## Step 5 — Vercel (React UI)

Vercel → **Add New → Project** → import the repo.

| Setting | Value |
|---|---|
| Framework preset | **Vite** |
| **Root directory** | **`frontend`** |
| Build command | `npm run build` (default) |
| Output directory | `dist` (default) |

Add one environment variable:

```bash
VITE_API_URL=https://<your-service>.onrender.com     # no trailing slash
```

`frontend/src/api.ts:5` reads it at build time, so **changing it later requires
a redeploy**, not just a restart. `frontend/vercel.json` supplies the SPA
rewrite so deep links like `/documents/abc` don't 404.

Deploy, and note the resulting `https://<project>.vercel.app`.

## Step 6 — Close the CORS loop

The API allowlists origins explicitly (it takes Bearer tokens, so a wildcard
would let any site drive a reviewer's session). Back in Render, set:

```bash
CRS_CORS_ALLOW_ORIGINS=https://<project>.vercel.app
```

Comma-separate to add Vercel preview URLs. Save — Render redeploys. Verify:

```bash
curl -s -o /dev/null -D - -X OPTIONS https://<your-service>.onrender.com/auth/login \
  -H "Origin: https://<project>.vercel.app" \
  -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin
```

## Step 7 — Seed and smoke-test

**Free instances have no dashboard shell or SSH** (paid tiers only), so seed
from your own machine against the same database and bucket. Everything the
seeder needs — `golden_set/`, the DB, R2 — is reachable locally:

```bash
cd backend
CRS_DATABASE_URL="<EXTERNAL database URL from Render>" \
CRS_S3_ENDPOINT_URL="https://<ACCOUNT_ID>.r2.cloudflarestorage.com" \
CRS_S3_ACCESS_KEY=<R2 key> CRS_S3_SECRET_KEY=<R2 secret> CRS_S3_REGION=auto \
AWS_REQUEST_CHECKSUM_CALCULATION=when_required \
CRS_DEMO_PASSWORD=<same value you set on Render> \
uv run python -m backend.seed_demo
```

Use the **External** database URL here, not the Internal one — the internal
hostname only resolves from inside Render's network.

This writes users, the PII master table, and the 22 contracts into the shared
database and bucket, and enqueues the jobs. The Render service's in-process
worker picks them up from there; nothing needs to run locally afterwards.

Idempotent, so re-running is safe. The master table is not optional — without
it every document halts in `pii_hold`, because it is the only masking
authority.

Then open the Vercel URL, log in as `reviewer1` with `CRS_DEMO_PASSWORD`, and
watch documents advance. Documents with *novel* planted PII deliberately stop in
`pii_hold` for resolution in PII Admin — that is the designed fail-closed
behaviour and the centrepiece of the demo (`docs/demo_script.md`).

---

## Troubleshooting

**Uploads fail with 400/501 from R2.** Recent boto3 sends checksum trailers R2
rejects. Confirm `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` is set.

**`You must specify a region`.** `CRS_S3_REGION=auto` is missing.

**Documents sit at `uploaded` forever.** `CRS_INLINE_WORKER=1` is not set, so
nothing is draining the queue — the API only enqueues.

**Documents stuck in `running` after a sleep/crash.** Expected on a host that
idles processes out, and self-healing: `jobs.requeue_orphaned` returns them to
`pending` at next startup. Hit the URL to wake the service.

**Pipeline silently stops but `/health` is fine.** Shouldn't happen — the loop
runs under a supervisor that restarts it with backoff and prints tracebacks to
the Render log. Check the logs for `[inline-worker] pipeline loop crashed`.

**Analysis errors about vector dimensions.** You switched embedding providers
against an existing index. Vectors are partitioned by `model_name`, so old
chunks are invisible to the new provider — re-index rather than mixing.

**First request of the day takes a minute.** Free-tier spin-down. Wake it before
the demo.

---

## Reverting to the full stack

Unset the five flags. `CRS_INLINE_WORKER` unset restores the standalone worker,
`CRS_EMBEDDING_PROVIDER` unset restores BGE-M3, and pointing `CRS_S3_*` /
`CRS_PRESIDIO_ANALYZER_URL` at in-VPC services restores MinIO/S3 and in-cluster
Presidio. Build without `CRS_EXTRAS` to get the full `ml` image back. That is
exactly what `docker compose up -d` and `render.yaml` already do.
