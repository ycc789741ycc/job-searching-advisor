"""Signing in with an outside identity — Google, today.

Google proves who someone is; we still decide which account that is and issue
our own session (ADR 0008). Two rules live here:

* **Which claims we accept.** The token's signature, issuer, audience and
  expiry are checked where it is decoded. What is left is ours to decide: the
  nonce must be the one this browser was sent off with, and the address must
  be one Google has verified — an unverified one proves nothing.
* **Which account a Google identity lands in.** An identity already linked
  signs straight in. Otherwise an account with the same address is *linked*,
  and because our own addresses were never verified, its password is removed:
  whoever registered the address first must not keep a way in once its real
  owner has proved it. A brand-new address creates an account.
"""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from enum import StrEnum


class FederatedProvider(StrEnum):
    GOOGLE = "google"


class SignInFailure(StrEnum):
    """Why a federated sign-in did not finish. Stable: the SPA maps these."""

    # The person declined on the consent screen.
    DECLINED = "declined"
    # The browser came back without the attempt this server started, or with
    # someone else's — the shape of a login cross-site request forgery.
    STATE_MISMATCH = "state_mismatch"
    # The attempt took longer than it may.
    EXPIRED = "expired"
    NONCE_MISMATCH = "nonce_mismatch"
    UNVERIFIED_EMAIL = "unverified_email"
    # The address belongs to an account already linked to a different Google
    # identity. Linking a second one would let either sign in as the other.
    ACCOUNT_CONFLICT = "account_conflict"
    # Google refused the code, or answered with something unusable.
    PROVIDER_FAILED = "provider_failed"
    NOT_CONFIGURED = "not_configured"


class FederatedSignInRejectedError(Exception):
    """A federated sign-in that must not produce a session."""

    def __init__(self, reason: SignInFailure, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True, slots=True)
class IdTokenClaims:
    """What we use from a decoded, signature-checked ID token."""

    subject: str
    email: str
    email_verified: bool
    nonce: str | None


def assert_acceptable_claims(claims: IdTokenClaims, *, expected_nonce: str) -> None:
    if claims.nonce is None or not hmac.compare_digest(claims.nonce, expected_nonce):
        raise FederatedSignInRejectedError(
            SignInFailure.NONCE_MISMATCH, "the sign-in answer was not for this attempt"
        )
    if not claims.subject:
        raise FederatedSignInRejectedError(
            SignInFailure.PROVIDER_FAILED, "the sign-in answer named no user"
        )
    if not claims.email or not claims.email_verified:
        raise FederatedSignInRejectedError(
            SignInFailure.UNVERIFIED_EMAIL, "Google has not verified this address"
        )


class AccountAction(StrEnum):
    SIGN_IN = "sign_in"
    LINK = "link"
    CREATE = "create"


@dataclass(frozen=True, slots=True)
class FederatedResolution:
    action: AccountAction
    account_id: uuid.UUID | None
    remove_password: bool = False


def resolve_federated_account(
    *,
    linked_account_id: uuid.UUID | None,
    email_account_id: uuid.UUID | None,
    email_account_has_password: bool,
    email_account_has_same_provider: bool,
) -> FederatedResolution:
    """Decide where a verified outside identity signs in.

    ``linked_account_id`` is the account this exact identity is already linked
    to; ``email_account_*`` describe the account holding the same address.
    """
    if linked_account_id is not None:
        return FederatedResolution(AccountAction.SIGN_IN, linked_account_id)
    if email_account_id is None:
        return FederatedResolution(AccountAction.CREATE, None)
    if email_account_has_same_provider:
        raise FederatedSignInRejectedError(
            SignInFailure.ACCOUNT_CONFLICT,
            "this address is already linked to a different Google account",
        )
    return FederatedResolution(
        AccountAction.LINK, email_account_id, remove_password=email_account_has_password
    )
