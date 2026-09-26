"""Private object storage for uploads and exports.

Keys are shaped ``users/{owner_id}/...`` and the bucket is private: a file is
only ever reachable through a short-lived signed URL
(docs/technical_boundaries.md section 3).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from kernel.config import MissingSecretError, Settings, must
from kernel.errors import ValidationError


class StorageUnavailableError(RuntimeError):
    """Object storage could not be reached within the start-up window."""


def object_key(owner_id: uuid.UUID, category: str, filename: str) -> str:
    """Build a key that cannot escape its owner's prefix."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValidationError("file name may not contain a path", filename=filename)
    if not category.isalnum():
        raise ValidationError("category must be alphanumeric", category=category)
    return f"users/{owner_id}/{category}/{filename}"


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        # Only `api` and `worker` build one of these; the crawler has no object
        # storage credentials at all.
        missing = [
            name
            for name in (
                "s3_endpoint_url",
                "s3_public_endpoint_url",
                "s3_region",
                "s3_bucket",
                "s3_access_key_id",
                "s3_secret_access_key",
            )
            if getattr(settings, name) is None
        ]
        if missing:
            raise MissingSecretError(
                "object storage is not configured on this process: "
                + ", ".join(sorted(name.upper() for name in missing))
            )
        access_key = must(settings.s3_access_key_id, "S3_ACCESS_KEY_ID")
        secret_key = must(settings.s3_secret_access_key, "S3_SECRET_ACCESS_KEY")
        self._bucket = must(settings.s3_bucket, "S3_BUCKET")
        region = must(settings.s3_region, "S3_REGION")
        self._ttl = settings.signed_url_ttl_seconds

        def client_for(endpoint: str) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key.get_secret_value(),
                aws_secret_access_key=secret_key.get_secret_value(),
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

        # Reads and writes go over the container network.
        self._client: Any = client_for(must(settings.s3_endpoint_url, "S3_ENDPOINT_URL"))
        # A presigned URL is signed against its own host, so it has to be signed
        # with the address the browser will actually use.
        self._signer: Any = (
            self._client
            if settings.s3_public_endpoint_url == settings.s3_endpoint_url
            else client_for(must(settings.s3_public_endpoint_url, "S3_PUBLIC_ENDPOINT_URL"))
        )

    def ensure_bucket(self, *, attempts: int = 10, delay_seconds: float = 1.0) -> None:
        """Idempotent; called once at startup so a fresh environment works.

        Retries briefly: object storage is a separate container and can be a
        second or two behind the process that needs it. That is an ordinary
        start-up condition, not a failure — but a persistent one still fails the
        start rather than leaving uploads broken at the first request.
        """
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
                if self._bucket not in existing:
                    self._client.create_bucket(Bucket=self._bucket)
                return
            except (BotoCoreError, ClientError) as exc:
                last = exc
                if attempt < attempts - 1:
                    time.sleep(delay_seconds)
        raise StorageUnavailableError(
            f"object storage did not become reachable after {attempts} attempts"
        ) from last

    def put(self, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=content_type)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return bytes(response["Body"].read())

    def signed_url(self, key: str) -> str:
        return str(
            self._signer.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._ttl,
            )
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
