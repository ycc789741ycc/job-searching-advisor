"""The SQLAlchemy side of identity's repositories, against a real database.

Worth proving here: entities survive their mappers, revocation is one
statement that touches only live tokens in the chain, the month's spend sums in
the database, and each event lands in the outbox as the dispatcher reads it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from advisor.identity.domain import (
    AccountFilter,
    AiUsageEntry,
    AiUsageEntryFilter,
    CredentialStatus,
    PasswordCredential,
    PasswordCredentialFilter,
    Provider,
    ProviderCredential,
    ProviderCredentialFailed,
    RefreshToken,
    RefreshTokenFilter,
    UsageBudgetExceeded,
)
from advisor.identity.infra.unit_of_work import SqlAlchemyIdentityUnitOfWork
from kernel.db import Database

pytestmark = pytest.mark.integration


def _token(account_id: uuid.UUID, family: uuid.UUID) -> RefreshToken:
    return RefreshToken.issued(
        account_id,
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        family_id=family,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


async def test_authentication_entities_round_trip(database: Database, account: uuid.UUID) -> None:
    uow = SqlAlchemyIdentityUnitOfWork(database)
    at = datetime(2026, 9, 27, tzinfo=UTC)

    async with uow.unauthenticated() as auth:
        assert await auth.accounts.get_count(AccountFilter(email="test@example.invalid")) >= 1
        found = await auth.accounts.get(account)
        assert found is not None and found.email == "test@example.invalid"
        password = await auth.passwords.create(
            PasswordCredential.set_for(account, password_hash="$argon2id$fake", at=at)
        )

    async with uow.for_owner(account) as mine:
        [loaded] = await mine.passwords.get_list(PasswordCredentialFilter(account_id=account))
        assert loaded == password
        found = await mine.accounts.get(account)
        assert found is not None
        found.pause_background_jobs("budget", at=at)
        paused = await mine.accounts.update(found)
        assert paused.background_jobs_paused_at == at and paused.paused_reason == "budget"


async def test_revoking_touches_only_live_tokens_in_the_chain(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyIdentityUnitOfWork(database)
    chain, other_chain = uuid.uuid4(), uuid.uuid4()
    async with uow.unauthenticated() as auth:
        first = await auth.refresh_tokens.create(_token(account, chain))
        await auth.refresh_tokens.create(_token(account, chain))
        untouched = await auth.refresh_tokens.create(_token(account, other_chain))

    async with uow.unauthenticated() as auth:
        chain_filter = RefreshTokenFilter(family_id=chain)
        assert await auth.refresh_tokens.revoke_all(chain_filter, at=datetime.now(UTC)) == 2
        # Already revoked: a second pass revokes nothing.
        assert await auth.refresh_tokens.revoke_all(chain_filter, at=datetime.now(UTC)) == 0
        [again] = await auth.refresh_tokens.get_list(
            RefreshTokenFilter(token_hash=first.token_hash)
        )
        assert again.revoked_at is not None
        live = await auth.refresh_tokens.get(untouched.id)
        assert live is not None and live.revoked_at is None

    async with uow.for_owner(account) as mine:
        assert (
            await mine.refresh_tokens.revoke_all(
                RefreshTokenFilter(account_id=account), at=datetime.now(UTC)
            )
            == 1
        )


async def test_the_months_spend_sums_in_the_database(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyIdentityUnitOfWork(database)
    now = datetime.now(UTC)

    def entry(owner: uuid.UUID, cost: str, at: datetime) -> AiUsageEntry:
        return AiUsageEntry(
            id=uuid.uuid4(),
            owner_id=owner,
            task="assessment",
            provider="anthropic",
            model="claude",
            template_version="v1",
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal(cost),
            occurred_at=at,
        )

    async with uow.for_owner(account) as mine:
        await mine.usage.create(entry(account, "0.25", now))
        await mine.usage.create(entry(account, "0.50", now))
        await mine.usage.create(entry(account, "9.00", now - timedelta(days=90)))
    async with uow.for_owner(other_account) as theirs:
        await theirs.usage.create(entry(other_account, "5.00", now))

    since = now - timedelta(days=1)
    async with uow.for_owner(account) as mine:
        spent = await mine.usage.total_cost(AiUsageEntryFilter(occurred_since=since))
        assert spent == Decimal("0.75")
        assert await mine.usage.get_count(AiUsageEntryFilter()) == 3
    async with uow.for_owner(uuid.uuid4()) as nobody:
        assert await nobody.usage.total_cost(AiUsageEntryFilter()) == Decimal(0)


async def test_identity_events_reach_the_outbox_as_the_dispatcher_reads_them(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyIdentityUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        credential = await mine.credentials.create(
            ProviderCredential.configured(
                account,
                provider=Provider.ANTHROPIC,
                model="claude",
                base_url=None,
                encrypted_api_key="ciphertext",
                last_four="1234",
            )
        )
        credential.failed("401")
        assert (await mine.credentials.update(credential)).status is CredentialStatus.FAILED
        mine.record(ProviderCredentialFailed(owner_id=account, reason="401"))
        mine.record(
            UsageBudgetExceeded(
                owner_id=account,
                cap_usd=Decimal("20"),
                spent_usd=Decimal("19.5"),
                estimated_usd=Decimal("1"),
            )
        )

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert sorted(rows.all()) == [
            ("ProviderCredentialFailed", {"reason": "401"}),
            (
                "UsageBudgetExceeded",
                {"cap_usd": "20", "spent_usd": "19.5", "estimated_usd": "1"},
            ),
        ]
