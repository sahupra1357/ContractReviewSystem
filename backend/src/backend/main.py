from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.auth_routes import router as auth_router
from backend.api.extract import router as extract_router
from backend.api.ingest import router as ingest_router
from backend.api.pii import router as pii_router
from backend.api.review import router as review_router
from backend.config import get_settings, require_valid_deployment_config

DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def allowed_origins() -> list[str]:
    """Vite dev origins plus any configured via CRS_CORS_ALLOW_ORIGINS.

    An explicit allowlist, never "*": the SPA sends a Bearer token, so a
    wildcard would let any site drive an authenticated reviewer's session.
    """
    configured = get_settings().cors_allow_origins
    extra = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return [*DEV_ORIGINS, *extra]


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail loudly on a half-configured deployment rather than silently dialling
    # localhost or signing tokens with the published dev secret.
    require_valid_deployment_config()
    # Hosts without a worker tier run the same pipeline loop in-process
    # (CRS_INLINE_WORKER=1). Off by default: compose and AWS run a real worker.
    if get_settings().inline_worker:
        from backend.worker import start_inline

        start_inline()
    yield


app = FastAPI(title="Contract Review Co-Pilot", version="0.1.0", lifespan=lifespan)
app.add_middleware(  # vite dev server locally; CRS_CORS_ALLOW_ORIGINS when split-hosted
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(ingest_router)
app.include_router(extract_router)
app.include_router(pii_router)
app.include_router(review_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}


# Built React UI (present in the container image; absent in local dev where
# `npm run dev` serves it instead). Hash routing → index.html only.
_static = get_settings().static_dir
if _static and Path(_static).is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
