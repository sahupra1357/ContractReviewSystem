"""Presidio analyzer on Modal — the PII tripwire for the free-tier demo.

Why this exists: the tripwire (backend/src/backend/pii/tripwire.py) is a
non-negotiable part of the PII gate — it is what makes the gate fail closed on
unregistered entities. It needs ~2GB for its spaCy model, which does not fit on
a small web host, so this moves it off-box instead of switching it off.

It serves the stock Presidio HTTP API, so the backend needs no code change:
just point CRS_PRESIDIO_ANALYZER_URL at the deployed URL.

    POST /analyze  {"text": "...", "language": "en"}
      -> [{"entity_type": "PERSON", "score": 0.85, "start": 0, "end": 4}, ...]

Deploy:
    pip install modal && modal setup
    modal deploy deploy/modal_presidio.py

This endpoint requires proxy auth (requires_proxy_auth=True) — without it the
URL alone lets anyone run analysis on your Modal credits. Create a token at
Modal dashboard → Settings → Proxy Auth Tokens, then set all three on the
backend:

    CRS_PRESIDIO_ANALYZER_URL=https://<workspace>--crs-presidio-analyzer-web.modal.run
    CRS_PRESIDIO_AUTH_KEY=wk-...
    CRS_PRESIDIO_AUTH_SECRET=ws-...

Verify with:
    curl -X POST <url>/analyze -H 'Content-Type: application/json' \
      -H 'Modal-Key: wk-...' -H 'Modal-Secret: ws-...' \
      -d '{"text":"Contact Gregory Alvarado","language":"en"}'

SYNTHETIC DATA ONLY. The text posted here is master-table-masked, but the whole
point of the tripwire is that it may still contain *unregistered* PII — that is
what it is looking for. Never point a real-contract deployment at a third-party
serverless host; the in-VPC build runs Presidio inside the VPC.
"""

import modal

# The official image already serves the API on :3000 under gunicorn, so we host
# it as-is rather than reimplementing the contract the tripwire depends on.
image = modal.Image.from_registry(
    "mcr.microsoft.com/presidio-analyzer:latest", add_python=None
).pip_install(
    # Modal installs its client into the image's Python, which leaves
    # typing_extensions older than the image's pydantic_core needs:
    #   ImportError: cannot import name 'Sentinel' from 'typing_extensions'
    # Presidio then fails at import and gunicorn serves nothing. Not needed
    # under docker compose, where nothing else is injected.
    "typing_extensions>=4.13",
)

app = modal.App("crs-presidio-analyzer", image=image)


@app.function(
    # spaCy's en_core_web_lg plus Presidio does not fit in 2GB: the gunicorn
    # worker was killed during import, leaving the master bound to :3000 with
    # nothing behind it — requests hung instead of failing.
    memory=4096,
    cpu=2.0,
    # Scale to zero between demos (free-tier friendly). The first request after
    # idle pays a ~10-30s cold start loading the model — within the tripwire's
    # 60s httpx timeout, but raise scaledown_window if the demo feels sluggish.
    scaledown_window=300,
    max_containers=2,
)
@modal.concurrent(max_inputs=10)
@modal.web_server(port=3000, startup_timeout=120, requires_proxy_auth=True)
def web():
    """Run the image's own entrypoint; Modal proxies :3000 to a public URL.

    /app/entrypoint.sh is `gunicorn -w $WORKERS -b 0.0.0.0:$PORT app:create_app()`
    — deliberately not reimplemented here, so the served API stays whatever the
    official image serves.
    """
    import os
    import subprocess

    # Inherit the image's environment and override only what we need. Passing a
    # fresh dict here strips HOME and poetry's variables, so `poetry run` cannot
    # find its virtualenv, gunicorn never binds, and Modal reports
    # "Cannot connect to host …:3000".
    subprocess.Popen(
        ["/app/entrypoint.sh"],
        cwd="/app",
        env={
            **os.environ,
            "PORT": "3000",
            "WORKERS": "1",
            # --preload loads spaCy in the master BEFORE binding, so a failed
            # model load is a visible crash instead of a socket that accepts
            # connections and never answers. The long timeout covers the model
            # load on a cold container; gunicorn's 30s default kills it.
            "GUNICORN_CMD_ARGS": "--preload --timeout 300 --graceful-timeout 60",
        },
    )
