"""Upload ingestion API — the POC's only document source (OQ-1 resolution).

Actor attribution: JWT bearer identity (backend.auth, Cognito-shaped seam).
Every upload is attributed and audited (Gate G1 requirement).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import CurrentActor
from backend.db import get_db
from backend.ingestion.core import ingest_document
from backend.storage import RawStorage, S3RawStorage

router = APIRouter(prefix="/ingest", tags=["ingestion"])


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
    actor: CurrentActor,
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[RawStorage, Depends(get_raw_storage)],
) -> UploadResponse:
    actor_id = actor.username
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
