"""Upload ingestion API — the POC's only document source (OQ-1 resolution).

Actor attribution: X-Actor-Id header. This is a PLACEHOLDER until Phase 6
brings Cognito-shaped JWT auth; the dependency is the single seam to swap.
Every upload is attributed and audited (Gate G1 requirement).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.ingestion.core import ingest_document
from backend.storage import RawStorage, S3RawStorage

router = APIRouter(prefix="/ingest", tags=["ingestion"])


def get_actor_id(x_actor_id: str | None = Header(default=None)) -> str:
    # Phase 6 replaces this with JWT-authenticated identity (Cognito-shaped).
    if not x_actor_id:
        raise HTTPException(status_code=401, detail="X-Actor-Id header required")
    return x_actor_id


def get_raw_storage() -> RawStorage:
    return S3RawStorage()


class UploadItemResult(BaseModel):
    filename: str
    document_id: str
    duplicate: bool
    sha256: str


class UploadResponse(BaseModel):
    results: list[UploadItemResult]


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile],
    actor_id: Annotated[str, Depends(get_actor_id)],
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[RawStorage, Depends(get_raw_storage)],
) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=422, detail="no files provided")

    results: list[UploadItemResult] = []
    for upload in files:
        data = await upload.read()
        if not data:
            raise HTTPException(
                status_code=422, detail=f"file '{upload.filename}' is empty"
            )
        outcome = ingest_document(
            session,
            storage,
            source="upload",
            filename=upload.filename or "unnamed",
            data=data,
            actor_id=actor_id,
            content_type=upload.content_type,
        )
        results.append(
            UploadItemResult(
                filename=upload.filename or "unnamed",
                document_id=outcome.document_id,
                duplicate=outcome.duplicate,
                sha256=outcome.sha256,
            )
        )
    session.commit()
    return UploadResponse(results=results)
