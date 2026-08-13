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

Then set, on the backend:
    CRS_PRESIDIO_ANALYZER_URL=https://<workspace>--crs-presidio-analyzer-web.modal.run

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
)

app = modal.App("crs-presidio-analyzer", image=image)


@app.function(
    # spaCy needs headroom; 2GB matches the plan the compose/render stacks use.
    memory=2048,
    cpu=1.0,
    # Scale to zero between demos (free-tier friendly). The first request after
    # idle pays a ~10-30s cold start loading the model — within the tripwire's
    # 60s httpx timeout, but raise scaledown_window if the demo feels sluggish.
    scaledown_window=300,
    max_containers=2,
)
@modal.concurrent(max_inputs=10)
@modal.web_server(port=3000, startup_timeout=120)
def web():
    """Run the image's own entrypoint; Modal proxies :3000 to a public URL.

    /app/entrypoint.sh is `gunicorn -w $WORKERS -b 0.0.0.0:$PORT app:create_app()`
    — deliberately not reimplemented here, so the served API stays whatever the
    official image serves.
    """
    import subprocess

    subprocess.Popen(
        ["/app/entrypoint.sh"],
        cwd="/app",
        env={"PORT": "3000", "WORKERS": "1", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )
