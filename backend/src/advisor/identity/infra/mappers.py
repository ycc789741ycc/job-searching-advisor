"""ORM rows to identity entities and back. No rules live here, only shape.

The owner-zone tables carry both ``owner_id`` (what row-level security keys
on) and ``account_id`` (the foreign key); for identity they are the same
account, so an entity holds one and the mapper writes both.
"""

from __future__ import annotations

from advisor.identity.domain import (
    Account,
    AiUsageBudget,
    AiUsageEntry,
    CredentialStatus,
    FederatedIdentity,
    PasswordCredential,
    Provider,
    ProviderCredential,
    RefreshToken,
)
from advisor.identity.infra import models


def account(row: models.Account) -> Account:
    return Account(
        id=row.id,
        email=row.email,
        background_jobs_paused_at=row.background_jobs_paused_at,
        paused_reason=row.paused_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def account_row(entity: Account) -> models.Account:
    row = models.Account(id=entity.id, auth_subject=None)
    apply_account(row, entity)
    return row


def apply_account(row: models.Account, entity: Account) -> None:
    row.email = entity.email
    row.background_jobs_paused_at = entity.background_jobs_paused_at
    row.paused_reason = entity.paused_reason


def password(row: models.PasswordCredential) -> PasswordCredential:
    return PasswordCredential(
        id=row.id,
        account_id=row.account_id,
        password_hash=row.password_hash,
        failed_attempts=row.failed_attempts,
        last_failed_at=row.last_failed_at,
        password_updated_at=row.password_updated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def password_row(entity: PasswordCredential) -> models.PasswordCredential:
    row = models.PasswordCredential(
        id=entity.id, owner_id=entity.account_id, account_id=entity.account_id
    )
    apply_password(row, entity)
    return row


def apply_password(row: models.PasswordCredential, entity: PasswordCredential) -> None:
    row.password_hash = entity.password_hash
    row.failed_attempts = entity.failed_attempts
    row.last_failed_at = entity.last_failed_at
    row.password_updated_at = entity.password_updated_at


def federated(row: models.FederatedIdentity) -> FederatedIdentity:
    return FederatedIdentity(
        id=row.id,
        account_id=row.account_id,
        provider=row.provider,
        subject=row.subject,
        email_at_link=row.email_at_link,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def federated_row(entity: FederatedIdentity) -> models.FederatedIdentity:
    row = models.FederatedIdentity(
        id=entity.id, owner_id=entity.account_id, account_id=entity.account_id
    )
    apply_federated(row, entity)
    return row


def apply_federated(row: models.FederatedIdentity, entity: FederatedIdentity) -> None:
    row.provider = entity.provider
    row.subject = entity.subject
    row.email_at_link = entity.email_at_link


def refresh_token(row: models.RefreshToken) -> RefreshToken:
    return RefreshToken(
        id=row.id,
        account_id=row.account_id,
        token_hash=row.token_hash,
        family_id=row.family_id,
        expires_at=row.expires_at,
        used_at=row.used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


def refresh_token_row(entity: RefreshToken) -> models.RefreshToken:
    row = models.RefreshToken(
        id=entity.id,
        owner_id=entity.account_id,
        account_id=entity.account_id,
        token_hash=entity.token_hash,
        family_id=entity.family_id,
    )
    apply_refresh_token(row, entity)
    return row


def apply_refresh_token(row: models.RefreshToken, entity: RefreshToken) -> None:
    row.expires_at = entity.expires_at
    row.used_at = entity.used_at
    row.revoked_at = entity.revoked_at


def credential(row: models.ProviderCredential) -> ProviderCredential:
    return ProviderCredential(
        id=row.id,
        owner_id=row.owner_id,
        provider=Provider(row.provider),
        model=row.model,
        base_url=row.base_url,
        encrypted_api_key=row.encrypted_api_key,
        last_four=row.last_four,
        status=CredentialStatus(row.status),
        last_error=row.last_error,
        last_verified_at=row.last_verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def credential_row(entity: ProviderCredential) -> models.ProviderCredential:
    row = models.ProviderCredential(id=entity.id, owner_id=entity.owner_id)
    apply_credential(row, entity)
    return row


def apply_credential(row: models.ProviderCredential, entity: ProviderCredential) -> None:
    row.provider = str(entity.provider)
    row.model = entity.model
    row.base_url = entity.base_url
    row.encrypted_api_key = entity.encrypted_api_key
    row.last_four = entity.last_four
    row.status = str(entity.status)
    row.last_error = entity.last_error
    row.last_verified_at = entity.last_verified_at


def budget(row: models.AiUsageBudget) -> AiUsageBudget:
    return AiUsageBudget(
        id=row.id,
        owner_id=row.owner_id,
        monthly_cap_usd=row.monthly_cap_usd,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def budget_row(entity: AiUsageBudget) -> models.AiUsageBudget:
    row = models.AiUsageBudget(id=entity.id, owner_id=entity.owner_id)
    apply_budget(row, entity)
    return row


def apply_budget(row: models.AiUsageBudget, entity: AiUsageBudget) -> None:
    row.monthly_cap_usd = entity.monthly_cap_usd


def usage(row: models.AiUsageLedger) -> AiUsageEntry:
    return AiUsageEntry(
        id=row.id,
        owner_id=row.owner_id,
        task=row.task,
        provider=row.provider,
        model=row.model,
        template_version=row.template_version,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        occurred_at=row.occurred_at,
    )


def usage_row(entity: AiUsageEntry) -> models.AiUsageLedger:
    row = models.AiUsageLedger(id=entity.id, owner_id=entity.owner_id, account_id=entity.owner_id)
    apply_usage(row, entity)
    return row


def apply_usage(row: models.AiUsageLedger, entity: AiUsageEntry) -> None:
    row.task = entity.task
    row.provider = entity.provider
    row.model = entity.model
    row.template_version = entity.template_version
    row.input_tokens = entity.input_tokens
    row.output_tokens = entity.output_tokens
    row.cost_usd = entity.cost_usd
    row.occurred_at = entity.occurred_at
