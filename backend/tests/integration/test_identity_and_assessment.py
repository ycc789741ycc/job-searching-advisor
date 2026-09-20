"""The path a user actually walks, against a real database.

The AI provider is stubbed — the point is the storage, the ownership checks and
the ledger, not the model.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import text

from kernel.ai_gateway import AiGateway
from kernel.ai_gateway.providers import REGISTRY, Completion, Request
from kernel.config import Settings
from kernel.db import Database
from modules.identity.public import IdentityService
from modules.profile.public import ProfileService
from modules.rolemap.public import RoleMapService

pytestmark = pytest.mark.integration


class StubProvider:
    """Stands in for a real model. Returns whatever the test queued.

    It replaces the *anthropic* registry entry rather than adding a new one, so
    the credential still goes through the same provider validation a real user
    would hit — a made-up provider name is correctly refused.
    """

    name = "anthropic"
    default_base_url = "https://llm.example.test"

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.calls: list[Request] = []

    async def complete(self, client: object, request: Request) -> Completion:
        self.calls.append(request)
        return Completion(
            text=self.replies.pop(0) if self.replies else "{}",
            input_tokens=1000,
            output_tokens=500,
            model=request.model,
        )

    async def stream(self, client: object, request: Request) -> AsyncIterator[str]:
        yield ""


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> StubProvider:
    provider = StubProvider()
    monkeypatch.setitem(REGISTRY, "anthropic", provider)
    return provider


@pytest.fixture
def identity(database: Database) -> IdentityService:
    return IdentityService(database, default_monthly_cap_usd=Decimal("20"))


# -- the credential ---------------------------------------------------------


async def test_the_stored_key_is_ciphertext_and_never_comes_back(
    database: Database, identity: IdentityService, account: uuid.UUID
) -> None:
    secret = "sk-ant-verysecretvalue1234"
    view = await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key=secret, base_url=None
    )

    assert view.last_four == "1234"
    read_back = await identity.credential(account)
    assert read_back is not None
    assert secret not in str(read_back)

    async with database.for_user(account) as session:
        stored = await session.execute(
            text(
                "SELECT encrypted_api_key FROM identity.provider_credential "
                "WHERE owner_id = :owner"
            ),
            {"owner": account},
        )
        ciphertext = stored.scalar_one()
    assert secret not in ciphertext


async def test_one_user_cannot_load_anothers_credential(
    identity: IdentityService, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    from kernel.errors import CredentialMissingError

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-mine", base_url=None
    )
    with pytest.raises(CredentialMissingError):
        await identity.load(other_account)


async def test_a_self_hosted_model_on_a_private_address_is_refused(
    identity: IdentityService, account: uuid.UUID
) -> None:
    """'Local' means a public URL the user controls, not our own network."""
    from kernel.errors import BlockedAddressError

    with pytest.raises(BlockedAddressError):
        await identity.set_credential(
            account,
            provider="local",
            model="llama",
            api_key="k",
            base_url="http://169.254.169.254/v1",
        )


# -- budget and ledger ------------------------------------------------------


async def test_every_call_lands_in_the_ledger_and_moves_the_budget(
    database: Database,
    identity: IdentityService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)

    from pydantic import BaseModel

    class Answer(BaseModel):
        ok: bool

    from kernel.ai_gateway.templates import PromptTemplate

    stub_provider.replies.append('{"ok": true}')
    await gateway.run(
        account,
        task="test.task",
        template=PromptTemplate("t", "v1", "sys", "do {{thing}}", 100),
        inputs={"thing": "something"},
        output_schema=Answer,
    )

    budget = await identity.budget(account)
    assert budget.spent_this_month_usd > 0
    assert budget.remaining_usd < budget.monthly_cap_usd

    async with database.for_user(account) as session:
        rows = await session.execute(
            text(
                "SELECT task, model, input_tokens, output_tokens "
                "FROM identity.ai_usage_ledger WHERE owner_id = :owner"
            ),
            {"owner": account},
        )
        entry = rows.one()
    assert entry.task == "test.task"
    assert (entry.input_tokens, entry.output_tokens) == (1000, 500)


async def test_a_call_past_the_cap_pauses_the_user_instead_of_running(
    database: Database,
    identity: IdentityService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    from kernel.errors import BudgetExceededError

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    await identity.set_budget(account, monthly_cap_usd=Decimal("0.000001"))
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)

    from pydantic import BaseModel

    from kernel.ai_gateway.templates import PromptTemplate

    class Answer(BaseModel):
        ok: bool

    with pytest.raises(BudgetExceededError):
        await gateway.run(
            account,
            task="test.task",
            template=PromptTemplate("t", "v1", "sys", "do {{thing}}", 100),
            inputs={"thing": "x"},
            output_schema=Answer,
        )

    assert stub_provider.calls == [], "no money may be spent past the cap"
    assert (await identity.account(account)).background_jobs_paused


# -- evidence and the assessment -------------------------------------------


@pytest.fixture
def profile(database: Database, settings: Settings) -> ProfileService:
    from kernel.storage import ObjectStore

    return ProfileService(
        database,
        object_store=ObjectStore(settings),
        connectors={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )


async def test_an_answer_becomes_evidence_and_bumps_the_profile_version(
    profile: ProfileService, account: uuid.UUID
) -> None:
    before = await profile.snapshot(account)
    await profile.record_answer(
        account,
        question_id="q1",
        question="Did you design the failover or execute it?",
        answer="I designed it",
    )
    after = await profile.snapshot(account)

    assert after.version == before.version + 1
    assert any("I designed it" in item.fact for item in after.evidence)
    assert any(item.source == "self_reported" for item in after.evidence)


async def test_an_assessment_citing_evidence_the_user_lacks_is_rejected(
    database: Database,
    identity: IdentityService,
    profile: ProfileService,
    settings: Settings,
    account: uuid.UUID,
    stub_provider: StubProvider,
) -> None:
    """The guard against invented claims, end to end."""
    from kernel.errors import EvidenceNotOwnedError
    from modules.assessment.public import AssessmentService
    from modules.market.public import MarketService

    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    await profile.record_answer(
        account, question_id="q1", question="Anything?", answer="Yes, plenty."
    )

    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
    rolemap = RoleMapService(
        database,
        market=MarketService(database, manual_refresh_per_day=3),
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
    )
    assessment = AssessmentService(
        database,
        profile=profile,
        rolemap=rolemap,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
    )

    dimensions = [
        {
            "id": f"d{i}",
            "name": f"Dimension {i}",
            "short_name": f"D{i}",
            "score": 70,
            "confidence": 0.9,
            "read": "A read.",
            # An id that belongs to nobody.
            "evidence_ids": ["00000000-0000-0000-0000-000000000000"],
        }
        for i in range(5)
    ]
    import json

    stub_provider.replies.append(json.dumps({"dimensions": dimensions}))

    with pytest.raises(EvidenceNotOwnedError, match="not in your profile"):
        await assessment.run(account)
