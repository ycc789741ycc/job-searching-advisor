"""Private object storage for uploads and exports.

Keys are shaped ``users/{owner_id}/...`` and the bucket is private: a file is
only ever reachable through a short-lived signed URL
(docs/technical_boundaries.md section 3).
"""

from __future__ import annotations

import uuid
from typing import Any

import boto3
from botocore.config import Config

from kernel.config import Settings
from kernel.errors import ValidationError


def object_key(owner_id: uuid.UUID, category: str, filename: str) -> str:
    """Build a key that cannot escape its owner's prefix."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValidationError("file name may not contain a path", filename=filename)
    if not category.isalnum():
        raise ValidationError("category must be alphanumeric", category=category)
    return f"users/{owner_id}/{category}/{filename}"


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._ttl = settings.signed_url_ttl_seconds
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        """Idempotent; called once at startup so a fresh environment works."""
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if self._bucket not in existing:
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=content_type)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return bytes(response["Body"].read())

    def signed_url(self, key: str) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._ttl,
            )
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
