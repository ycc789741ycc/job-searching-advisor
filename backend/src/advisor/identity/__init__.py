"""The identity component.

Accounts, sign-in (password and Google), sessions, and the user's AI credential
and budget.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``identity-public-surface``).
"""

from advisor.identity._domain import (
    FederatedSignInRejectedError,
    SignInFailure,
)
from advisor.identity._infra.google import (
    ATTEMPT_TTL_SECONDS as GOOGLE_ATTEMPT_TTL_SECONDS,
)
from advisor.identity._service import (
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
]
