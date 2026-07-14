from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.auth_routes import router as auth_router
from backend.api.extract import router as extract_router
from backend.api.ingest import router as ingest_router
from backend.api.pii import router as pii_router
from backend.api.review import router as review_router
from backend.config import get_settings

app = FastAPI(title="Contract Review Co-Pilot", version="0.1.0")
app.add_middleware(  # React dev server (vite) during local development
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
