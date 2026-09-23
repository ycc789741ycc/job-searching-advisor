"""The only path to an LLM in this system.

    estimate cost -> within budget? -> decrypt credential -> provider adapter
    -> validate against output schema -> write usage ledger -> return result

Used by ``api`` (streaming chat, from Phase 3) and by ``worker`` jobs. Modules
never import a provider adapter directly; an import-linter contract enforces
that (docs/technical_boundaries.md section 5).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from kernel.ai_gateway import pricing, templates
from kernel.ai_gateway.ports import BudgetGuard, CredentialStore, UsageRecord
from kernel.ai_gateway.providers import REGISTRY, Request
from kernel.ai_gateway.templates import PromptTemplate
from kernel.config import Settings
from kernel.crypto import decrypt
from kernel.errors import (
    CredentialFailedError,
    OutputInvalidError,
    ProviderUnavailableError,
    ValidationError,
)
from kernel.fetch import GuardedClient
from kernel.logging import get_logger

T = TypeVar("T", bound=BaseModel)

log = get_logger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_MIN_OUTPUT_TOKENS = 4_096
_MAX_OUTPUT_TOKENS = 16_000


@dataclass(frozen=True, slots=True)
class Result[TModel: BaseModel]:
    """A validated answer, plus what produced it.

    ``model_id`` and ``template_version`` are stored on every AI-derived
    snapshot so a user who switches models can be shown why results changed
    (domain section 2.8).
    """

    value: TModel
    model_id: str
    template_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class StreamText:
    """Prose from a structured stream, safe to show as it arrives."""

    text: str


@dataclass(frozen=True, slots=True)
class StreamResult[TModel: BaseModel]:
    """The validated object that ends a structured stream."""

    value: TModel
    model_id: str
    template_version: str


@dataclass(frozen=True, slots=True)
class Estimate:
    """What a call would cost, before any money is spent."""

    input_tokens: int
    expected_output_tokens: int
    cost_usd: Decimal
    model_id: str
    template_version: str
    rate_is_published: bool


class AiGateway:
    def __init__(
        self,
        *,
        settings: Settings,
        credentials: CredentialStore,
        budget: BudgetGuard,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._budget = budget

    # -- internals ----------------------------------------------------------

    def _client(self) -> GuardedClient:
        return GuardedClient(
            timeout_seconds=self._settings.ai_request_timeout_seconds,
            user_agent=self._settings.service_name,
        )

    async def _prepare(
        self,
        owner_id: uuid.UUID,
        template: PromptTemplate,
        inputs: dict[str, str],
        untrusted: frozenset[str],
    ) -> tuple[Request, pricing.CostEstimate]:
        credential = await self._credentials.load(owner_id)
        provider = REGISTRY.get(credential.provider)
        if provider is None:
            raise ValidationError(
                f"unknown AI provider {credential.provider!r}", provider=credential.provider
            )

        prompt = template.render(inputs, untrusted=untrusted)
        estimate = pricing.estimate(
            credential.model,
            prompt=template.system + prompt,
            expected_output_tokens=template.expected_output_tokens,
        )

        base_url = credential.base_url or provider.default_base_url
        if not base_url:
            raise ValidationError("this provider needs a base URL", provider=credential.provider)

        # The key is opened here and lives only for this call.
        api_key = decrypt(credential.encrypted_api_key, context=str(owner_id))
        request = Request(
            api_key=api_key,
            model=credential.model,
            base_url=base_url,
            system=template.system,
            user=prompt,
            max_output_tokens=min(
                _MAX_OUTPUT_TOKENS, max(_MIN_OUTPUT_TOKENS, template.expected_output_tokens * 2)
            ),
        )
        return request, estimate

    # -- public surface -----------------------------------------------------

    async def estimate(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        untrusted: frozenset[str] = frozenset(),
    ) -> Estimate:
        """Price a call without making it.

        This is what the first-analysis and first-role-map confirmations show.
        """
        credential = await self._credentials.load(owner_id)
        prompt = template.render(inputs, untrusted=untrusted)
        cost = pricing.estimate(
            credential.model,
            prompt=template.system + prompt,
            expected_output_tokens=template.expected_output_tokens,
        )
        log.info("ai.estimate", task=task, template=template.version_id, model=credential.model)
        return Estimate(
            input_tokens=cost.input_tokens,
            expected_output_tokens=cost.output_tokens,
            cost_usd=cost.cost_usd,
            model_id=credential.model,
            template_version=template.version_id,
            rate_is_published=cost.rate_is_published,
        )

    async def run(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        output_schema: type[T],
        untrusted: frozenset[str] = frozenset(),
    ) -> Result[T]:
        request, estimate = await self._prepare(owner_id, template, inputs, untrusted)
        await self._budget.check(owner_id, estimate.cost_usd)

        provider = REGISTRY[(await self._credentials.load(owner_id)).provider]
        attempts = self._settings.ai_max_output_retries + 1
        last_error: Exception | None = None

        async with self._client() as client:
            for attempt in range(attempts):
                try:
                    completion = await provider.complete(client, request)
                except CredentialFailedError as exc:
                    await self._credentials.mark_failed(owner_id, exc.message)
                    raise
                except ProviderUnavailableError:
                    raise

                cost = pricing.cost_of(
                    completion.model,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                )
                # The ledger records every call, including one whose output we
                # then reject — the provider billed for it either way.
                await self._budget.record(
                    UsageRecord(
                        owner_id=owner_id,
                        task=task,
                        provider=provider.name,
                        model=completion.model,
                        template_version=template.version_id,
                        input_tokens=completion.input_tokens,
                        output_tokens=completion.output_tokens,
                        cost_usd=cost,
                    )
                )

                try:
                    value = _parse(completion.text, output_schema)
                except OutputInvalidError as exc:
                    last_error = exc
                    log.warning(
                        "ai.output_invalid",
                        task=task,
                        template=template.version_id,
                        attempt=attempt + 1,
                    )
                    request = _with_repair_note(request, str(exc))
                    continue

                return Result(
                    value=value,
                    model_id=completion.model,
                    template_version=template.version_id,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    cost_usd=cost,
                )

        raise OutputInvalidError(
            f"{task}: the model did not return output matching the schema after "
            f"{attempts} attempts",
            task=task,
            template=template.version_id,
        ) from last_error

    async def stream(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        untrusted: frozenset[str] = frozenset(),
    ) -> AsyncIterator[str]:
        """Token-by-token output, for the resume chat.

        Budget and credential handling are identical to :meth:`run`; only
        schema validation is absent, because the caller is rendering text.
        """
        request, estimate = await self._prepare(owner_id, template, inputs, untrusted)
        await self._budget.check(owner_id, estimate.cost_usd)
        credential = await self._credentials.load(owner_id)
        provider = REGISTRY[credential.provider]

        text_length = 0
        async with self._client() as client:
            try:
                async for chunk in provider.stream(client, request):
                    text_length += len(chunk)
                    yield chunk
            except CredentialFailedError as exc:
                await self._credentials.mark_failed(owner_id, exc.message)
                raise

        output_tokens = pricing.estimate_tokens("x" * text_length)
        await self._budget.record(
            UsageRecord(
                owner_id=owner_id,
                task=task,
                provider=provider.name,
                model=credential.model,
                template_version=template.version_id,
                input_tokens=estimate.input_tokens,
                output_tokens=output_tokens,
                cost_usd=pricing.cost_of(
                    credential.model,
                    input_tokens=estimate.input_tokens,
                    output_tokens=output_tokens,
                ),
            )
        )

    async def stream_structured(
        self,
        owner_id: uuid.UUID,
        *,
        task: str,
        template: PromptTemplate,
        inputs: dict[str, str],
        output_schema: type[T],
        marker: str,
        untrusted: frozenset[str] = frozenset(),
    ) -> AsyncIterator[StreamText | StreamResult[T]]:
        """Prose as it arrives, then one validated object.

        The template asks for the reply followed by ``marker`` and a JSON
        object. Text before the marker streams to the caller; the marker never
        does. The JSON is validated against ``output_schema`` exactly as
        :meth:`run` would, and ends the stream as a :class:`StreamResult`.

        There is no retry: the prose has already been shown, so a second
        attempt would contradict it. Invalid output raises
        ``OutputInvalidError`` after the text.
        """
        credential = await self._credentials.load(owner_id)
        pending = ""
        tail: str | None = None
        async for chunk in self.stream(
            owner_id, task=task, template=template, inputs=inputs, untrusted=untrusted
        ):
            if tail is not None:
                tail += chunk
                continue
            release, tail = _split_at_marker(pending + chunk, marker)
            pending = "" if tail is not None else (pending + chunk)[len(release) :]
            if release:
                yield StreamText(release)
        if tail is None:
            if pending:
                yield StreamText(pending)
            raise OutputInvalidError("the reply ended without its structured part")
        yield StreamResult(
            value=_parse(tail, output_schema),
            model_id=credential.model,
            template_version=template.version_id,
        )


def _split_at_marker(buffer: str, marker: str) -> tuple[str, str | None]:
    """Text safe to release now, and what follows the marker if it has come.

    Text is held back while it could still be the start of the marker, so no
    part of the marker ever reaches the reader.
    """
    at = buffer.find(marker)
    if at >= 0:
        return buffer[:at], buffer[at + len(marker) :]
    for keep in range(min(len(marker) - 1, len(buffer)), 0, -1):
        if marker.startswith(buffer[-keep:]):
            return buffer[:-keep], None
    return buffer, None


def _parse[TOut: BaseModel](text: str, schema: type[TOut]) -> TOut:
    """Turn model output into a validated object, or reject it.

    Output is untrusted like any other external text, so nothing is used before
    it validates.
    """
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        # Some models prepend a sentence before the object.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start > 0 and end > start:
            candidate = candidate[start : end + 1]

    try:
        payload = json.loads(candidate)
    except ValueError as exc:
        raise OutputInvalidError("model output was not JSON") from exc

    try:
        return schema.model_validate(payload)
    except PydanticValidationError as exc:
        raise OutputInvalidError(f"model output did not match the schema: {exc.errors()}") from exc


def _with_repair_note(request: Request, problem: str) -> Request:
    """Tell the model what was wrong, without letting its own output steer it."""
    note = (
        "\n\nYour previous reply could not be used. "
        f"{templates.fence('validation_error', problem)}\n"
        "Reply again with only a JSON object matching the schema. No prose, no code fence."
    )
    return Request(
        api_key=request.api_key,
        model=request.model,
        base_url=request.base_url,
        system=request.system,
        user=request.user + note,
        max_output_tokens=request.max_output_tokens,
    )
