from fastapi import FastAPI

from backend.config import get_settings

app = FastAPI(title="Contract Review Co-Pilot", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": get_settings().environment}
