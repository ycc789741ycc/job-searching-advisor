"""The identity component.

Accounts, sign-in (password and Google), sessions, and the user's AI credential
and budget.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``identity-public-surface``).
"""

from advisor.identity.domain import (
    FederatedSignInRejectedError,
    SignInFailure,
)
from advisor.identity.factory import create_auth_service, create_identity_service
from advisor.identity.infra.google import (
    ATTEMPT_TTL_SECONDS as GOOGLE_ATTEMPT_TTL_SECONDS,
)
from advisor.identity.service import (
    SUGGESTED_MODELS,
    AccountView,
    AuthService,
    BudgetView,
    CredentialView,
    GoogleEndpoints,
    GoogleOidc,
    GoogleSignIn,
    GoogleStart,
    IdentityService,
    Provider,
    Session,
)

__all__ = [
    "GOOGLE_ATTEMPT_TTL_SECONDS",
    "SUGGESTED_MODELS",
    "AccountView",
    "AuthService",
    "BudgetView",
    "CredentialView",
    "FederatedSignInRejectedError",
    "GoogleEndpoints",
    "GoogleOidc",
    "GoogleSignIn",
    "GoogleStart",
    "IdentityService",
    "Provider",
    "Session",
    "SignInFailure",
    "create_auth_service",
    "create_identity_service",
]
