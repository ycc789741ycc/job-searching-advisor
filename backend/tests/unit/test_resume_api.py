"""The Resume Advisor at the HTTP edge: queued, streamed, refused in the envelope.

Runs the real router and error handlers in-process against a stand-in service —
no network, no infra, no queue.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import errors
from app.dependencies import current_user, get_container
from domain.resume import Bullet, Position, ResumeContent
from kernel.errors import TargetUnusableError
from modules.resume import api as resume_api
from modules.resume.public import (
    Options,
    ResumeSummaryView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    Template,
)
from modules.target.public import TargetKind, TargetRef

RESUME_ID = uuid.uuid4()
REVISION_ID = uuid.uuid4()


class FakeResumes:
    def __init__(self) -> None:
        self.refuse = False
        self.requested: list[tuple[TargetRef, Template, Options]] = []
        self.fail_revision = False

    async def request(
        self, owner_id: uuid.UUID, ref: TargetRef, *, template: Template, options: Options
    ) -> ResumeSummaryView:
        if self.refuse:
            raise TargetUnusableError("paste its job description instead")
        self.requested.append((ref, template, options))
        return ResumeSummaryView(
            id=RESUME_ID,
            target=ref,
            label="Staff Platform Engineer · Meridian Labs",
            status="drafting",
            error_code=None,
            error_message=None,
            latest_version=None,
            created_at=datetime(2026, 9, 23, tzinfo=UTC),
            updated_at=datetime(2026, 9, 23, tzinfo=UTC),
        )

    async def revise(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, request: str, content: dict[str, Any]
    ) -> AsyncIterator[object]:
        yield RevisionText("Shorter, ")
        yield RevisionText("and it leads with reliability.")
        if self.fail_revision:
            yield RevisionFailed("ai_output_invalid", "the proposed revision was rejected")
            return
        yield RevisionDone(
            revision_id=REVISION_ID,
            reply="Shorter, and it leads with reliability.",
            proposal=ResumeContent(
                name="Maya",
                headline="",
                contact="",
                summary="Short.",
                experience=(Position("Engineer", "Kestrel", "2022", (Bullet("x", ("e1",)),)),),
            ),
        )


@pytest.fixture
def resumes() -> FakeResumes:
    return FakeResumes()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(resume_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def client(resumes: FakeResumes, queued: list[dict[str, Any]]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(resume_api.router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(resume=resumes)
    return TestClient(app, raise_server_exceptions=False)


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body into (event, data) pairs."""
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_writing_a_resume_queues_it_with_its_template_and_options(
    client: TestClient, resumes: FakeResumes, queued: list[dict[str, Any]]
) -> None:
    target = str(uuid.uuid4())
    response = client.post(
        "/tailored-resumes",
        json={
            "kind": "privatePosting",
            "id": target,
            "template": "brief",
            "options": {"trim": True},
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "drafting"
    [(ref, template, options)] = resumes.requested
    assert (ref.kind, ref.id, template) == (TargetKind.PRIVATE_POSTING, target, Template.BRIEF)
    assert options == Options(metrics=True, reorder=True, trim=True)
    assert [(job["name"], job["resume_id"]) for job in queued] == [
        ("resume.generate", str(RESUME_ID))
    ]


def test_a_target_that_cannot_be_written_for_is_refused_before_queueing(
    client: TestClient, resumes: FakeResumes, queued: list[dict[str, Any]]
) -> None:
    resumes.refuse = True
    body = {"kind": "subscription", "id": str(uuid.uuid4())}
    response = client.post("/tailored-resumes", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "target_unusable"
    assert queued == []


def test_an_unknown_template_is_refused_in_the_envelope(client: TestClient) -> None:
    response = client.post(
        "/tailored-resumes",
        json={"kind": "matchedPosting", "id": str(uuid.uuid4()), "template": "neon"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_chat_streams_text_then_one_proposal(client: TestClient) -> None:
    response = client.post(
        f"/tailored-resumes/{RESUME_ID}/revisions",
        json={"message": "Make the summary shorter", "content": {"name": "Maya"}},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _events(response.text)
    assert [name for name, _ in events] == ["text", "text", "proposal"]
    assert "".join(data["text"] for name, data in events if name == "text") == (
        "Shorter, and it leads with reliability."
    )
    proposal = events[-1][1]
    assert proposal["revision_id"] == str(REVISION_ID)
    assert proposal["proposal"]["summary"] == "Short."


def test_a_rejected_revision_ends_the_stream_with_a_coded_error(
    client: TestClient, resumes: FakeResumes
) -> None:
    resumes.fail_revision = True
    response = client.post(
        f"/tailored-resumes/{RESUME_ID}/revisions",
        json={"message": "Invent a promotion", "content": {"name": "Maya"}},
    )
    events = _events(response.text)
    assert events[-1] == (
        "error",
        {"code": "ai_output_invalid", "message": "the proposed revision was rejected"},
    )
    assert "proposal" not in [name for name, _ in events]


def test_an_empty_chat_message_is_refused(client: TestClient) -> None:
    response = client.post(
        f"/tailored-resumes/{RESUME_ID}/revisions", json={"message": "", "content": {}}
    )
    assert response.status_code == 422
