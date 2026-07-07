"""Object storage (MinIO locally → S3 in production, design doc §7).

RawStorage is a Protocol so the ingestion core is testable without MinIO.
Only the ingestion and extraction stages may touch the raw bucket
(invariant #1) — downstream stages read the masked bucket exclusively.
"""

from typing import Protocol

import boto3
import botocore.exceptions

from backend.config import get_settings


def _client_and_bucket(bucket: str):
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    # idempotent: platforms without the compose minio-init step (e.g. Render)
    # get their buckets on first use
    try:
        client.head_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError:
        try:
            client.create_bucket(Bucket=bucket)
        except botocore.exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
    return client, bucket


class RawStorage(Protocol):
    def put_raw(self, key: str, data: bytes, content_type: str | None) -> None: ...

    def get_raw(self, key: str) -> bytes: ...


class MaskedStorage(Protocol):
    """The masked zone — written ONLY by the mask stage; the ONLY zone
    downstream stages (index/analyze) are ever handed (invariant #1)."""

    def put_masked(self, key: str, data: bytes, content_type: str | None) -> None: ...

    def get_masked(self, key: str) -> bytes: ...


class S3RawStorage:
    def __init__(self) -> None:
        self._client, self._bucket = _client_and_bucket(get_settings().s3_bucket_raw)

    def put_raw(self, key: str, data: bytes, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def get_raw(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()


class S3MaskedStorage:
    def __init__(self) -> None:
        self._client, self._bucket = _client_and_bucket(
            get_settings().s3_bucket_masked
        )

    def put_masked(self, key: str, data: bytes, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def get_masked(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()
