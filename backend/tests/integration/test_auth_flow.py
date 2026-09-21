"""Registration, sign-in, rotation and lockout, against a real database."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from kernel.auth import ALGORITHM, StaticSecretResolver, TokenVerifier
from kernel.db import Database
from kernel.errors import ConflictError, RateLimitedError, UnauthenticatedError, ValidationError
from modules.identity.domain import MAX_FAILED_ATTEMPTS
from modules.identity.public import AuthService

pytestmark = pytest.mark.integration

SECRET = "t" * 48
PASSWORD = "a perfectly fine passphrase"


@pytest.fixture
def auth(database: Database) -> AuthService:
    return AuthService(
        database,
        secret=SECRET,
        issuer="jsa-test",
        audience="jsa-test-api",
        access_ttl_seconds=900,
        refresh_ttl_days=30,
        default_monthly_cap_usd=Decimal("20"),
    )


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(
        issuer="jsa-test",
        audience="jsa-test-api",
        resolver=StaticSecretResolver(SECRET),
        algorithms=(ALGORITHM,),
    )


@pytest_asyncio.fixture
async def address(database: Database):
    """A unique address per test, cleaned up with everything it owns."""
    email = f"test-{uuid.uuid4().hex[:12]}@example.invalid"
    yield email
    async with database.shared() as session:
        result = await session.execute(
            text("SELECT id FROM identity.account WHERE email = :e"), {"e": email}
        )
        row = result.scalar_one_or_none()
    if row is not None:
        from app.models import OWNER_ZONE_TABLES

        async with database.for_user(row) as session:
            for table in OWNER_ZONE_TABLES:
                await session.execute(text(f"DELETE FROM {table} WHERE owner_id = :o"), {"o": row})
        async with database.shared() as session:
            await session.execute(text("DELETE FROM identity.account WHERE id = :i"), {"i": row})


# -- registration -----------------------------------------------------------


async def test_registering_signs_you_in(
    auth: AuthService, verifier: TokenVerifier, address: str
) -> None:
    session = await auth.register(email=address, password=PASSWORD)

    assert session.email == address
    user = verifier.verify(session.access_token)
    assert user.subject == str(session.account_id)
    assert user.email == address


async def test_registration_creates_the_budget_the_ai_gateway_needs(
    auth: AuthService, database: Database, address: str
) -> None:
    session = await auth.register(email=address, password=PASSWORD)
    async with database.for_user(session.account_id) as db:
        count = await db.execute(
            text("SELECT count(*) FROM identity.ai_usage_budget WHERE owner_id = :o"),
            {"o": session.account_id},
        )
        assert count.scalar_one() == 1


async def test_the_password_is_never_stored_in_the_clear(
    auth: AuthService, database: Database, address: str
) -> None:
    session = await auth.register(email=address, password=PASSWORD)
    async with database.for_user(session.account_id) as db:
        stored = await db.execute(
            text("SELECT password_hash FROM identity.password_credential WHERE owner_id = :o"),
            {"o": session.account_id},
        )
        value = stored.scalar_one()
    assert PASSWORD not in value
    assert value.startswith("$argon2id$")


async def test_the_same_address_cannot_register_twice(auth: AuthService, address: str) -> None:
    await auth.register(email=address, password=PASSWORD)
    with pytest.raises(ConflictError, match="already exists"):
        await auth.register(email=address.upper(), password=PASSWORD)


async def test_a_weak_password_is_refused_before_an_account_exists(
    auth: AuthService, database: Database, address: str
) -> None:
    with pytest.raises(ValidationError):
        await auth.register(email=address, password="short")
    async with database.shared() as session:
        count = await session.execute(
            text("SELECT count(*) FROM identity.account WHERE email = :e"), {"e": address}
        )
        assert count.scalar_one() == 0


# -- sign in ----------------------------------------------------------------


async def test_signing_in_with_the_right_password_works(auth: AuthService, address: str) -> None:
    registered = await auth.register(email=address, password=PASSWORD)
    signed_in = await auth.sign_in(email=address, password=PASSWORD)
    assert signed_in.account_id == registered.account_id


async def test_the_address_is_matched_however_it_was_typed(auth: AuthService, address: str) -> None:
    await auth.register(email=address, password=PASSWORD)
    assert await auth.sign_in(email=f"  {address.upper()} ", password=PASSWORD)


async def test_a_wrong_password_and_an_unknown_address_look_identical(
    auth: AuthService, address: str
) -> None:
    """Telling them apart turns sign-in into a way to discover who has an account."""
    await auth.register(email=address, password=PASSWORD)

    with pytest.raises(UnauthenticatedError) as wrong:
        await auth.sign_in(email=address, password="a different passphrase")
    with pytest.raises(UnauthenticatedError) as unknown:
        await auth.sign_in(email="nobody@example.invalid", password=PASSWORD)

    assert str(wrong.value) == str(unknown.value)


async def test_repeated_failures_lock_the_account_then_let_it_back_in(
    auth: AuthService, database: Database, address: str
) -> None:
    session = await auth.register(email=address, password=PASSWORD)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(UnauthenticatedError):
            await auth.sign_in(email=address, password="wrong passphrase here")

    with pytest.raises(RateLimitedError, match="Too many failed attempts"):
        await auth.sign_in(email=address, password=PASSWORD)

    # The lock is time-based, so pushing the clock back releases it.
    async with database.for_user(session.account_id) as db:
        await db.execute(
            text(
                "UPDATE identity.password_credential "
                "SET last_failed_at = now() - interval '1 hour' WHERE owner_id = :o"
            ),
            {"o": session.account_id},
        )
    assert await auth.sign_in(email=address, password=PASSWORD)


async def test_a_successful_sign_in_clears_the_failure_count(
    auth: AuthService, database: Database, address: str
) -> None:
    session = await auth.register(email=address, password=PASSWORD)
    with pytest.raises(UnauthenticatedError):
        await auth.sign_in(email=address, password="wrong passphrase here")
    await auth.sign_in(email=address, password=PASSWORD)

    async with database.for_user(session.account_id) as db:
        attempts = await db.execute(
            text("SELECT failed_attempts FROM identity.password_credential WHERE owner_id = :o"),
            {"o": session.account_id},
        )
        assert attempts.scalar_one() == 0


# -- refresh rotation -------------------------------------------------------


async def test_refreshing_returns_a_new_pair(auth: AuthService, address: str) -> None:
    first = await auth.register(email=address, password=PASSWORD)
    second = await auth.refresh(refresh_token=first.refresh_token)

    assert second.account_id == first.account_id
    assert second.refresh_token != first.refresh_token


async def test_the_refresh_token_is_stored_hashed(
    auth: AuthService, database: Database, address: str
) -> None:
    session = await auth.register(email=address, password=PASSWORD)
    async with database.for_user(session.account_id) as db:
        stored = await db.execute(
            text("SELECT token_hash FROM identity.refresh_token WHERE owner_id = :o"),
            {"o": session.account_id},
        )
        hashes = [row for row in stored.scalars()]
    assert session.refresh_token not in hashes


async def test_reusing_a_spent_token_revokes_the_whole_chain(
    auth: AuthService, address: str
) -> None:
    """Theft is indistinguishable from replay, so the safe move is to end both."""
    first = await auth.register(email=address, password=PASSWORD)
    second = await auth.refresh(refresh_token=first.refresh_token)

    with pytest.raises(UnauthenticatedError, match="already used"):
        await auth.refresh(refresh_token=first.refresh_token)

    # The replacement is gone too, so the thief gains nothing either.
    with pytest.raises(UnauthenticatedError, match="signed out"):
        await auth.refresh(refresh_token=second.refresh_token)


async def test_an_unknown_refresh_token_is_refused(auth: AuthService) -> None:
    with pytest.raises(UnauthenticatedError, match="sign in again"):
        await auth.refresh(refresh_token="not-a-real-token")


# -- sign out ---------------------------------------------------------------


async def test_signing_out_ends_the_session(auth: AuthService, address: str) -> None:
    session = await auth.register(email=address, password=PASSWORD)
    await auth.sign_out(refresh_token=session.refresh_token)
    with pytest.raises(UnauthenticatedError):
        await auth.refresh(refresh_token=session.refresh_token)


async def test_signing_out_is_idempotent_and_never_an_error(auth: AuthService) -> None:
    await auth.sign_out(refresh_token=None)
    await auth.sign_out(refresh_token="already-gone")


async def test_signing_out_everywhere_ends_every_session(auth: AuthService, address: str) -> None:
    first = await auth.register(email=address, password=PASSWORD)
    second = await auth.sign_in(email=address, password=PASSWORD)

    revoked = await auth.sign_out_everywhere(first.account_id)
    assert revoked >= 2

    for session in (first, second):
        with pytest.raises(UnauthenticatedError):
            await auth.refresh(refresh_token=session.refresh_token)
