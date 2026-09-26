"""Registration, sign-in and session refresh.

We run our own sign-in, so this module owns the whole flow: hashing, lockout,
token issuance and refresh rotation. Signing in with Google ends here too: the
Google exchange (``advisor.identity.google``) proves who someone is, and
``sign_in_with_google`` decides which account that is and issues *our* session
(ADR 0008).

Two things it deliberately does not do, because both need email delivery and
that is still an open question in docs/technical_boundaries.md section 8:

* **Address verification.** Anyone can register with an address they do not
  own. Nothing is sent to it yet, so the exposure is limited — but it must be
  in place before any notification feature ships.
* **Password reset.** There is no way back in for someone who forgets. Users
  should be told this rather than discovering it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from advisor.identity.domain import (
    AccountAction,
    FederatedProvider,
    IdTokenClaims,
    LockoutState,
    RefreshRejectedError,
    RefreshTokenState,
    WeakPasswordError,
    access_token_expiry,
    assert_acceptable,
    new_refresh_token,
    normalize_email,
    refresh_token_expiry,
    resolve_federated_account,
)
from advisor.identity.infra.auth_repository import AuthRepository, digest
from advisor.identity.infra.models import (
    Account,
    AiUsageBudget,
    FederatedIdentity,
    PasswordCredential,
    RefreshToken,
)
from advisor.identity.infra.passwords import (
    dummy_verify,
    hash_password,
    needs_rehash,
    verify_password,
)
from kernel.auth import issue_access_token
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import ConflictError, RateLimitedError, UnauthenticatedError, ValidationError
from kernel.logging import get_logger

log = get_logger(__name__)

# Deliberately identical for "no such account" and "wrong password": telling
# them apart turns sign-in into a way to discover who has an account.
_BAD_CREDENTIALS = "That email and password do not match."


@dataclass(frozen=True, slots=True)
class _SignInOutcome:
    """Decided inside the transaction, acted on once it has committed."""

    account_id: uuid.UUID | None = None
    failure: str | None = None
    locked_until: str | None = None


@dataclass(frozen=True, slots=True)
class Session:
    """What a successful sign-in produces."""

    account_id: uuid.UUID
    email: str
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class AuthService:
    def __init__(
        self,
        database: Database,
        *,
        secret: str,
        issuer: str,
        audience: str,
        access_ttl_seconds: int,
        refresh_ttl_days: int,
        default_monthly_cap_usd: object,
    ) -> None:
        self._db = database
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl_days = refresh_ttl_days
        self._default_cap = default_monthly_cap_usd

    # -- registration -------------------------------------------------------

    async def register(self, *, email: str, password: str) -> Session:
        address = normalize_email(email)
        if "@" not in address or address.startswith("@") or address.endswith("@"):
            raise ValidationError("That does not look like an email address.")
        try:
            assert_acceptable(password, email=address)
        except WeakPasswordError as exc:
            raise ValidationError(str(exc)) from exc

        now = utcnow()
        # The account row has to be found and created before there is an
        # app.user_id, so this runs in a session with none set. The policies on
        # these tables allow exactly that and nothing else.
        async with self._db.shared() as session:
            repo = AuthRepository(session)
            if await repo.account_by_email(address) is not None:
                raise ConflictError("An account already exists for that email.")

            account = Account(email=address, auth_subject=None)
            session.add(account)
            await session.flush()

            repo.add_credential(
                PasswordCredential(
                    owner_id=account.id,
                    account_id=account.id,
                    password_hash=hash_password(password),
                    password_updated_at=now,
                )
            )
            account_id = account.id

        # The budget is ordinary owner-zone data, so it is written in a scoped
        # session. Only the two authentication tables have the bootstrap
        # exception, and only because they are read before an identity exists.
        async with self._db.for_user(account_id) as session:
            session.add(AiUsageBudget(owner_id=account_id, monthly_cap_usd=self._default_cap))

        log.info("auth.registered", account_id=str(account_id))
        return await self._start_session(account_id, address, now=now)

    # -- sign in ------------------------------------------------------------

    async def sign_in(self, *, email: str, password: str) -> Session:
        address = normalize_email(email)
        now = utcnow()

        # Raising inside the transaction would roll back the very thing we just
        # recorded — the failed-attempt counter — so lockout would never engage.
        # The outcome is decided inside, committed, and acted on afterwards.
        outcome: _SignInOutcome

        async with self._db.shared() as session:
            repo = AuthRepository(session)
            account = await repo.account_by_email(address)
            credential = await repo.credential_for(account.id) if account is not None else None

            if account is None or credential is None:
                # Spend the same work as a real check so the response time does
                # not reveal whether the address is registered.
                dummy_verify()
                outcome = _SignInOutcome(failure=_BAD_CREDENTIALS)
            else:
                lockout = LockoutState(
                    failed_attempts=credential.failed_attempts,
                    last_failed_at=credential.last_failed_at,
                )
                if lockout.is_locked(now=now):
                    unlocks = lockout.unlocks_at(now=now)
                    outcome = _SignInOutcome(locked_until=unlocks.isoformat() if unlocks else None)
                elif not verify_password(credential.password_hash, password):
                    failed = lockout.after_failure(now=now)
                    credential.failed_attempts = failed.failed_attempts
                    credential.last_failed_at = failed.last_failed_at
                    log.info(
                        "auth.sign_in_failed",
                        account_id=str(account.id),
                        attempts=failed.failed_attempts,
                    )
                    outcome = _SignInOutcome(failure=_BAD_CREDENTIALS)
                else:
                    cleared = lockout.after_success()
                    credential.failed_attempts = cleared.failed_attempts
                    credential.last_failed_at = cleared.last_failed_at
                    # The only moment the plaintext is available to rehash with.
                    if needs_rehash(credential.password_hash):
                        credential.password_hash = hash_password(password)
                        credential.password_updated_at = now
                    outcome = _SignInOutcome(account_id=account.id)

        if outcome.locked_until is not None:
            raise RateLimitedError(
                "Too many failed attempts. Try again shortly.",
                unlocks_at=outcome.locked_until,
            )
        if outcome.failure is not None:
            raise UnauthenticatedError(outcome.failure)

        assert outcome.account_id is not None
        log.info("auth.signed_in", account_id=str(outcome.account_id))
        return await self._start_session(outcome.account_id, address, now=now)

    # -- sign in with Google ------------------------------------------------

    async def sign_in_with_google(self, claims: IdTokenClaims) -> Session:
        """Sign in the account a verified Google identity belongs to.

        ``claims`` must already have passed ``assert_acceptable_claims``: the
        address is one Google has verified. That is what lets a matching
        password account be linked — and why its password is removed, since
        our own addresses never were verified (ADR 0008).
        """
        provider = str(FederatedProvider.GOOGLE)
        address = normalize_email(claims.email)
        now = utcnow()
        created = False

        # Like registration, this runs before there is an app.user_id. The
        # authentication tables' policies allow exactly that.
        async with self._db.shared() as session:
            repo = AuthRepository(session)
            linked = await repo.federated_identity(provider, claims.subject)
            by_email = await repo.account_by_email(address) if linked is None else None
            resolution = resolve_federated_account(
                linked_account_id=linked.account_id if linked is not None else None,
                email_account_id=by_email.id if by_email is not None else None,
                email_account_has_password=(
                    by_email is not None and await repo.credential_for(by_email.id) is not None
                ),
                email_account_has_same_provider=(
                    by_email is not None
                    and await repo.federated_identity_for(by_email.id, provider) is not None
                ),
            )

            if resolution.action is AccountAction.CREATE:
                account = Account(email=address, auth_subject=None)
                session.add(account)
                await session.flush()
                account_id = account.id
                created = True
            else:
                assert resolution.account_id is not None
                account_id = resolution.account_id

            if resolution.action is not AccountAction.SIGN_IN:
                repo.add_federated_identity(
                    FederatedIdentity(
                        owner_id=account_id,
                        account_id=account_id,
                        provider=provider,
                        subject=claims.subject,
                        email_at_link=address,
                    )
                )

            if resolution.remove_password:
                # Whoever registered this address before its owner proved it
                # loses the password and every session it opened.
                await repo.delete_credential_for(account_id)
                revoked = await repo.revoke_all_for(account_id, at=now)
                log.warning(
                    "auth.google_linked",
                    account_id=str(account_id),
                    password_removed=True,
                    sessions_revoked=revoked,
                )
            elif resolution.action is AccountAction.LINK:
                log.info("auth.google_linked", account_id=str(account_id), password_removed=False)

            email = address
            if linked is not None:
                existing = await session.get(Account, account_id)
                email = existing.email if existing is not None else address

        if created:
            async with self._db.for_user(account_id) as session:
                session.add(AiUsageBudget(owner_id=account_id, monthly_cap_usd=self._default_cap))
            log.info("auth.registered", account_id=str(account_id), method=provider)

        log.info("auth.signed_in", account_id=str(account_id), method=provider)
        return await self._start_session(account_id, email, now=now)

    # -- refresh ------------------------------------------------------------

    async def refresh(self, *, refresh_token: str) -> Session:
        """Exchange a refresh token for a new pair, retiring the old one.

        Rotation is what makes theft detectable: a token is single-use, so
        seeing one twice means the chain is compromised and all of it goes.

        As in sign_in, the rejection is raised *after* the transaction commits —
        otherwise revoking the compromised family would be rolled back by the
        very exception that reports it, and the stolen chain would stay alive.
        """
        now = utcnow()
        rejection: str | None = None
        account_id: uuid.UUID | None = None
        address = ""
        family: uuid.UUID | None = None

        async with self._db.shared() as session:
            repo = AuthRepository(session)
            stored = await repo.refresh_token(refresh_token)
            if stored is None:
                rejection = "Please sign in again."
            else:
                state = RefreshTokenState(
                    expires_at=stored.expires_at,
                    revoked_at=stored.revoked_at,
                    used_at=stored.used_at,
                )
                try:
                    state.assert_usable(now=now)
                except RefreshRejectedError as exc:
                    rejection = str(exc)
                    if stored.used_at is not None:
                        revoked = await repo.revoke_family(stored.family_id, at=now)
                        log.warning(
                            "auth.refresh_token_reused",
                            account_id=str(stored.owner_id),
                            revoked=revoked,
                        )
                else:
                    stored.used_at = now
                    account = await session.get(Account, stored.account_id)
                    if account is None:
                        rejection = "Please sign in again."
                    else:
                        account_id = account.id
                        address = account.email
                        family = stored.family_id

        if rejection is not None or account_id is None or family is None:
            raise UnauthenticatedError(rejection or "Please sign in again.")

        return await self._start_session(account_id, address, now=now, family_id=family)

    # -- sign out -----------------------------------------------------------

    async def sign_out(self, *, refresh_token: str | None) -> None:
        """Idempotent: signing out twice, or with nothing, is not an error."""
        if not refresh_token:
            return
        now = utcnow()
        async with self._db.shared() as session:
            repo = AuthRepository(session)
            stored = await repo.refresh_token(refresh_token)
            if stored is not None:
                await repo.revoke_family(stored.family_id, at=now)

    async def sign_out_everywhere(self, account_id: uuid.UUID) -> int:
        now = utcnow()
        async with self._db.for_user(account_id) as session:
            return await AuthRepository(session).revoke_all_for(account_id, at=now)

    # -- internals ----------------------------------------------------------

    async def _start_session(
        self,
        account_id: uuid.UUID,
        email: str,
        *,
        now: datetime,
        family_id: uuid.UUID | None = None,
    ) -> Session:
        token = new_refresh_token()
        refresh_expires = refresh_token_expiry(now=now, ttl_days=self._refresh_ttl_days)

        async with self._db.shared() as session:
            AuthRepository(session).add_refresh_token(
                RefreshToken(
                    owner_id=account_id,
                    account_id=account_id,
                    token_hash=digest(token),
                    family_id=family_id or uuid.uuid4(),
                    expires_at=refresh_expires,
                )
            )

        access = issue_access_token(
            secret=self._secret,
            subject=account_id,
            email=email,
            issuer=self._issuer,
            audience=self._audience,
            ttl_seconds=self._access_ttl,
            now=now,
        )
        return Session(
            account_id=account_id,
            email=email,
            access_token=access,
            access_expires_at=access_token_expiry(now=now, ttl_seconds=self._access_ttl),
            refresh_token=token,
            refresh_expires_at=refresh_expires,
        )
