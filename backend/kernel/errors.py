"""Typed errors with stable codes.

Nothing in this code base raises a bare ``Exception`` or swallows one. Every
failure carries a stable ``code`` that the API layer maps to an HTTP status and
returns to the client; internal detail and stack traces never cross that
boundary (design-guideline shared-context: Errors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    # Generic
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    UNAUTHENTICATED = "unauthenticated"
    VALIDATION_FAILED = "validation_failed"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    # AI gateway
    BUDGET_EXCEEDED = "ai_budget_exceeded"
    CREDENTIAL_MISSING = "ai_credential_missing"
    CREDENTIAL_FAILED = "ai_credential_failed"
    PROVIDER_UNAVAILABLE = "ai_provider_unavailable"
    OUTPUT_INVALID = "ai_output_invalid"
    # Evidence / assessment
    EVIDENCE_NOT_OWNED = "evidence_not_owned"
    DIMENSION_COUNT_INVALID = "dimension_count_invalid"
    # Fetch
    BLOCKED_ADDRESS = "blocked_address"
    UPSTREAM_FAILED = "upstream_failed"
    # Market
    SOURCE_UNSUPPORTED = "source_unsupported"


class DomainError(Exception):
    """Base class for every expected failure in this system."""

    code: ErrorCode = ErrorCode.VALIDATION_FAILED

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def _error(name: str, code: ErrorCode) -> type[DomainError]:
    return type(name, (DomainError,), {"code": code})


NotFoundError = _error("NotFoundError", ErrorCode.NOT_FOUND)
ForbiddenError = _error("ForbiddenError", ErrorCode.FORBIDDEN)
UnauthenticatedError = _error("UnauthenticatedError", ErrorCode.UNAUTHENTICATED)
ValidationError = _error("ValidationError", ErrorCode.VALIDATION_FAILED)
ConflictError = _error("ConflictError", ErrorCode.CONFLICT)
RateLimitedError = _error("RateLimitedError", ErrorCode.RATE_LIMITED)

BudgetExceededError = _error("BudgetExceededError", ErrorCode.BUDGET_EXCEEDED)
CredentialMissingError = _error("CredentialMissingError", ErrorCode.CREDENTIAL_MISSING)
CredentialFailedError = _error("CredentialFailedError", ErrorCode.CREDENTIAL_FAILED)
ProviderUnavailableError = _error("ProviderUnavailableError", ErrorCode.PROVIDER_UNAVAILABLE)
OutputInvalidError = _error("OutputInvalidError", ErrorCode.OUTPUT_INVALID)

EvidenceNotOwnedError = _error("EvidenceNotOwnedError", ErrorCode.EVIDENCE_NOT_OWNED)
DimensionCountError = _error("DimensionCountError", ErrorCode.DIMENSION_COUNT_INVALID)

BlockedAddressError = _error("BlockedAddressError", ErrorCode.BLOCKED_ADDRESS)
UpstreamFailedError = _error("UpstreamFailedError", ErrorCode.UPSTREAM_FAILED)

SourceUnsupportedError = _error("SourceUnsupportedError", ErrorCode.SOURCE_UNSUPPORTED)


HTTP_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.BUDGET_EXCEEDED: 402,
    ErrorCode.CREDENTIAL_MISSING: 412,
    ErrorCode.CREDENTIAL_FAILED: 502,
    ErrorCode.PROVIDER_UNAVAILABLE: 502,
    ErrorCode.OUTPUT_INVALID: 502,
    ErrorCode.EVIDENCE_NOT_OWNED: 422,
    ErrorCode.DIMENSION_COUNT_INVALID: 422,
    ErrorCode.BLOCKED_ADDRESS: 400,
    ErrorCode.UPSTREAM_FAILED: 502,
    ErrorCode.SOURCE_UNSUPPORTED: 422,
}


@dataclass(frozen=True, slots=True)
class Failure:
    """A failure carried as a value rather than raised, for ``Result`` flows."""

    code: ErrorCode
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, error: DomainError) -> Failure:
        return cls(code=error.code, message=error.message, context=error.context)
