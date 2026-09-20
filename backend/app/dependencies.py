"""Request-scoped dependencies: who is calling, and what they may use."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header

from app.container import Container, container
from kernel.errors import UnauthenticatedError
from kernel.logging import trace_id_var


def get_container() -> Container:
    return container()


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    deps: Container = Depends(get_container),
) -> uuid.UUID:
    """Verify the JWT and resolve it to a local account id.

    Signature, issuer, audience and expiry are checked on every request.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthenticatedError("a bearer token is required")

    user = deps.verifier.verify(authorization.split(" ", 1)[1].strip())
    account = await deps.identity.ensure_account(auth_subject=user.subject, email=user.email)
    trace_id_var.set(str(account.id))
    return account.id


CurrentUser = Annotated[uuid.UUID, Depends(current_user)]
Deps = Annotated[Container, Depends(get_container)]
