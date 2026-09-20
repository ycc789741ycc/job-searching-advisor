"""The gateway's contract: budget first, schema always, ledger every call."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from pydantic import BaseModel

from kernel.ai_gateway import templates
from kernel.ai_gateway.gateway import AiGateway
from kernel.ai_gateway.ports import ProviderCredential, UsageRecord
from kernel.ai_gateway.providers import REGISTRY, Completion, Request
from kernel.config import get_settings
from kernel.crypto import encrypt
from kernel.errors import (
    BudgetExceededError,
    CredentialFailedError,
    OutputInvalidError,
)

OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")


class Answer(BaseModel):
    name: str
    score: int


class StubCredentials:
    def __init__(self, encrypted_key: str) -> None:
        self.failures: list[str] = []
        self._credential = ProviderCredential(
            provider="stub",
            model="claude-opus-5",
            base_url="https://llm.example.com",
            encrypted_api_key=encrypted_key,
            owner_id=OWNER,
        )

    async def load(self, owner_id: uuid.UUID) -> ProviderCredential:
        return self._credential

    async def mark_failed(self, owner_id: uuid.UUID, reason: str) -> None:
        self.failures.append(reason)


class StubBudget:
    def __init__(self, *, cap: Decimal | None = None) -> None:
        self.cap = cap
        self.recorded: list[UsageRecord] = []
        self.checked: list[Decimal] = []

    async def check(self, owner_id: uuid.UUID, estimated_cost_usd: Decimal) -> None:
        self.checked.append(estimated_cost_usd)
        if self.cap is not None and estimated_cost_usd > self.cap:
            raise BudgetExceededError("monthly cap would be exceeded", cap=str(self.cap))

    async def record(self, usage: UsageRecord) -> None:
        self.recorded.append(usage)


class StubProvider:
    name = "stub"
    default_base_url = "https://llm.example.com"

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.requests: list[Request] = []

    async def complete(self, client: object, request: Request) -> Completion:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=reply, input_tokens=120, output_tokens=40, model=request.model)

    async def stream(self, client: object, request: Request) -> AsyncIterator[str]:
        self.requests.append(request)
        for reply in self.replies:
            assert isinstance(reply, str)
            yield reply


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch):
    def install(replies: list[str | Exception]) -> StubProvider:
        provider = StubProvider(replies)
        monkeypatch.setitem(REGISTRY, "stub", provider)
        return provider

    return install


@pytest.fixture
def gateway(clean_env: None) -> tuple[AiGateway, StubCredentials, StubBudget]:
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    budget = StubBudget()
    return AiGateway(settings=get_settings(), credentials=credentials, budget=budget), (
        credentials
    ), budget


TEMPLATE = templates.PromptTemplate(
    name="stub_task",
    version="v1",
    system="Return JSON.",
    user="Analyse {{subject}}.",
    expected_output_tokens=100,
)


async def test_valid_output_returns_value_with_model_and_template_version(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    stub_provider(['{"name": "API design", "score": 81}'])

    result = await gw.run(
        OWNER,
        task="assess",
        template=TEMPLATE,
        inputs={"subject": "a backend engineer"},
        output_schema=Answer,
    )

    assert result.value == Answer(name="API design", score=81)
    assert result.model_id == "claude-opus-5"
    assert result.template_version == "stub_task@v1"
    assert len(budget.recorded) == 1


async def test_budget_is_checked_before_the_provider_is_called(
    clean_env: None, stub_provider
) -> None:
    credentials = StubCredentials(encrypt("sk-test-key", context=str(OWNER)))
    budget = StubBudget(cap=Decimal("0.0000001"))
    gw = AiGateway(settings=get_settings(), credentials=credentials, budget=budget)
    provider = stub_provider(['{"name": "x", "score": 1}'])

    with pytest.raises(BudgetExceededError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"},
            output_schema=Answer,
        )
    assert provider.requests == [], "no money may be spent once the cap is hit"


async def test_output_that_misses_the_schema_is_retried_then_rejected(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(['{"name": "x"}', "not json at all", '{"score": "high"}'])

    with pytest.raises(OutputInvalidError, match="after 3 attempts"):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"},
            output_schema=Answer,
        )

    assert len(provider.requests) == 3
    assert len(budget.recorded) == 3, "the provider billed for every attempt, so log every attempt"


async def test_a_retry_tells_the_model_what_was_wrong(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    provider = stub_provider(["nonsense", '{"name": "API design", "score": 81}'])

    result = await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert result.value.score == 81
    assert "could not be used" in provider.requests[1].user
    assert '<data name="validation_error">' in provider.requests[1].user


async def test_json_wrapped_in_a_code_fence_is_accepted(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, _ = gateway
    stub_provider(['Here you go:\n```json\n{"name": "API design", "score": 81}\n```'])
    result = await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )
    assert result.value.name == "API design"


async def test_a_rejected_key_is_reported_and_pauses_the_user(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, credentials, _ = gateway
    stub_provider([CredentialFailedError("the provider rejected this API key")])

    with pytest.raises(CredentialFailedError):
        await gw.run(
            OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"},
            output_schema=Answer,
        )
    assert credentials.failures == ["the provider rejected this API key"]


async def test_the_decrypted_key_reaches_the_provider_and_nothing_else(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider(['{"name": "x", "score": 1}'])

    await gw.run(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}, output_schema=Answer
    )

    assert provider.requests[0].api_key == "sk-test-key"
    assert "sk-test-key" not in str(budget.recorded[0])


async def test_estimate_prices_a_call_without_making_one(
    gateway: tuple[AiGateway, StubCredentials, StubBudget], stub_provider
) -> None:
    gw, _, budget = gateway
    provider = stub_provider([])

    estimate = await gw.estimate(
        OWNER, task="assess", template=TEMPLATE, inputs={"subject": "x"}
    )

    assert estimate.cost_usd > 0
    assert estimate.model_id == "claude-opus-5"
    assert estimate.rate_is_published is True
    assert provider.requests == [] and budget.recorded == []
