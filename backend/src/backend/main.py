from fastapi import FastAPI

from backend.api.ingest import router as ingest_router
from backend.api.pii import router as pii_router
from backend.config import get_settings

app = FastAPI(title="Contract Review Co-Pilot", version="0.1.0")
app.include_router(ingest_router)
app.include_router(pii_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}
