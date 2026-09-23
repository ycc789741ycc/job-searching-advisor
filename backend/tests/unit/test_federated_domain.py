"""Which Google answers we accept, and which account each one lands in."""

from __future__ import annotations

import uuid

import pytest

from domain.identity import (
    AccountAction,
    FederatedSignInRejectedError,
    IdTokenClaims,
    SignInFailure,
    assert_acceptable_claims,
    resolve_federated_account,
)

NONCE = "the-nonce-this-browser-was-sent-with"
ACCOUNT = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _claims(**overrides: object) -> IdTokenClaims:
    values: dict[str, object] = {
        "subject": "google-sub-1",
        "email": "person@example.com",
        "email_verified": True,
        "nonce": NONCE,
    }
    values.update(overrides)
    return IdTokenClaims(**values)  # type: ignore[arg-type]


# -- claims -----------------------------------------------------------------


def test_a_verified_address_with_this_attempts_nonce_is_accepted() -> None:
    assert_acceptable_claims(_claims(), expected_nonce=NONCE)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"nonce": "someone-elses"}, SignInFailure.NONCE_MISMATCH),
        ({"nonce": None}, SignInFailure.NONCE_MISMATCH),
        ({"email_verified": False}, SignInFailure.UNVERIFIED_EMAIL),
        ({"email": ""}, SignInFailure.UNVERIFIED_EMAIL),
        ({"subject": ""}, SignInFailure.PROVIDER_FAILED),
    ],
)
def test_an_answer_that_proves_nothing_is_refused(
    overrides: dict[str, object], reason: SignInFailure
) -> None:
    with pytest.raises(FederatedSignInRejectedError) as caught:
        assert_acceptable_claims(_claims(**overrides), expected_nonce=NONCE)
    assert caught.value.reason is reason


# -- which account ------------------------------------------------------------


def test_an_identity_already_linked_signs_in_to_its_account() -> None:
    resolution = resolve_federated_account(
        linked_account_id=ACCOUNT,
        email_account_id=None,
        email_account_has_password=False,
        email_account_has_same_provider=False,
    )
    assert resolution.action is AccountAction.SIGN_IN
    assert resolution.account_id == ACCOUNT
    assert not resolution.remove_password


def test_a_new_address_creates_an_account() -> None:
    resolution = resolve_federated_account(
        linked_account_id=None,
        email_account_id=None,
        email_account_has_password=False,
        email_account_has_same_provider=False,
    )
    assert resolution.action is AccountAction.CREATE
    assert resolution.account_id is None


def test_a_password_account_at_the_same_address_is_linked_and_loses_its_password() -> None:
    """Our addresses were never verified, so whoever registered this one first
    must not keep a way in once Google has proved who owns it."""
    resolution = resolve_federated_account(
        linked_account_id=None,
        email_account_id=ACCOUNT,
        email_account_has_password=True,
        email_account_has_same_provider=False,
    )
    assert resolution.action is AccountAction.LINK
    assert resolution.account_id == ACCOUNT
    assert resolution.remove_password


def test_an_address_linked_to_another_google_identity_is_refused() -> None:
    with pytest.raises(FederatedSignInRejectedError) as caught:
        resolve_federated_account(
            linked_account_id=None,
            email_account_id=ACCOUNT,
            email_account_has_password=False,
            email_account_has_same_provider=True,
        )
    assert caught.value.reason is SignInFailure.ACCOUNT_CONFLICT
