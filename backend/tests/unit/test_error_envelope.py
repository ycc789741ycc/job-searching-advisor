"""Every failure reaches the client in one envelope, with no internals.

Runs the real handlers on a throwaway app in-process — no network, no infra.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, EmailStr

from app import errors
from kernel.errors import ConflictError


class Body(BaseModel):
    email: EmailStr


def client() -> TestClient:
    app = FastAPI()
    errors.install(app)

    @app.post("/echo")
    async def echo(body: Body) -> dict[str, str]:
        return {"email": str(body.email)}

    @app.post("/conflict")
    async def conflict() -> None:
        raise ConflictError("An account already exists for that email.")

    @app.post("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    return TestClient(app, raise_server_exceptions=False)


def test_a_bad_request_body_names_the_field_in_one_sentence() -> None:
    """A sign-up form shows this directly; it must not have to parse a list."""
    response = client().post("/echo", json={"email": "not-an-address"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"].startswith("email:")


def test_a_missing_field_is_named() -> None:
    response = client().post("/echo", json={})
    assert response.json()["error"]["message"].startswith("email:")


def test_a_domain_error_keeps_its_stable_code_and_message() -> None:
    response = client().post("/conflict")
    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "An account already exists for that email."}
    }


def test_an_unexpected_error_leaks_nothing() -> None:
    response = client().post("/boom")
    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert response.json()["error"]["code"] == "internal_error"
