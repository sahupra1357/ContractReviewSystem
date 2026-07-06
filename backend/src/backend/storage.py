"""Object storage (MinIO locally → S3 in production, design doc §7).

RawStorage is a Protocol so the ingestion core is testable without MinIO.
Only the ingestion and extraction stages may touch the raw bucket
(invariant #1) — downstream stages read the masked bucket exclusively.
"""

from typing import Protocol

import boto3

from backend.config import get_settings


class RawStorage(Protocol):
    def put_raw(self, key: str, data: bytes, content_type: str | None) -> None: ...


class S3RawStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        self._bucket = settings.s3_bucket_raw

    def put_raw(self, key: str, data: bytes, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)
