"""Object key safety and start-up tolerance."""

from __future__ import annotations

import uuid

import pytest
from botocore.exceptions import EndpointConnectionError

from kernel.errors import ValidationError
from kernel.storage import ObjectStore, object_key
from kernel.storage.objects import StorageUnavailableError

OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_a_key_is_scoped_to_its_owner() -> None:
    assert object_key(OWNER, "resumes", "abc") == f"users/{OWNER}/resumes/abc"


@pytest.mark.parametrize("name", ["../secrets", "a/b", "a\\b", "..", "x/../y"])
def test_a_file_name_cannot_escape_its_owner_prefix(name: str) -> None:
    with pytest.raises(ValidationError, match="may not contain a path"):
        object_key(OWNER, "resumes", name)


def test_a_category_must_be_alphanumeric() -> None:
    with pytest.raises(ValidationError, match="alphanumeric"):
        object_key(OWNER, "res/umes", "abc")


class FlakyClient:
    """Fails the first `failures` calls, as a container that is still starting."""

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.created: list[str] = []

    def list_buckets(self) -> dict[str, list[dict[str, str]]]:
        if self.remaining > 0:
            self.remaining -= 1
            raise EndpointConnectionError(endpoint_url="http://objectstore:9000/")
        return {"Buckets": []}

    def create_bucket(self, Bucket: str) -> None:  # noqa: N803 - boto3's own name
        self.created.append(Bucket)


def store_with(client: object) -> ObjectStore:
    """An ObjectStore with a stubbed client, built without touching settings.

    ensure_bucket's retry behaviour is what is under test here; constructing a
    real one would need credentials and reach the network.
    """
    store = ObjectStore.__new__(ObjectStore)
    object.__setattr__(store, "_bucket", "test-bucket")
    object.__setattr__(store, "_client", client)
    return store


def test_a_briefly_unreachable_store_is_waited_for() -> None:
    client = FlakyClient(failures=3)
    store_with(client).ensure_bucket(attempts=10, delay_seconds=0)
    assert client.created == ["test-bucket"]


def test_a_persistently_unreachable_store_fails_the_start() -> None:
    """Tolerating a slow start is not the same as ignoring a broken one."""
    client = FlakyClient(failures=99)
    with pytest.raises(StorageUnavailableError, match="did not become reachable"):
        store_with(client).ensure_bucket(attempts=3, delay_seconds=0)


def test_an_existing_bucket_is_left_alone() -> None:
    class Existing(FlakyClient):
        def list_buckets(self) -> dict[str, list[dict[str, str]]]:
            return {"Buckets": [{"Name": "test-bucket"}]}

    client = Existing(failures=0)
    store_with(client).ensure_bucket(attempts=1, delay_seconds=0)
    assert client.created == []
