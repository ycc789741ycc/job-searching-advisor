"""Password hashing.

Argon2id with the parameters OWASP lists first. Kept behind a tiny interface so
the cost can be raised later without touching a call site, and so rehashing on
sign-in is automatic when it is.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP's first recommendation for Argon2id: 19 MiB, 2 iterations, 1 lane.
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Constant-time as far as the library allows; never raises on a mismatch."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash used weaker parameters than we use now.

    Checked on every successful sign-in, which is the only moment the plaintext
    is available to rehash with.
    """
    try:
        return bool(_hasher.check_needs_rehash(stored_hash))
    except InvalidHashError:
        return True


def dummy_verify() -> None:
    """Burn the same work as a real verification.

    Called when no account exists for an address, so that "unknown email" and
    "wrong password" take the same time and the endpoint cannot be used to
    discover who has an account.
    """
    verify_password(
        "$argon2id$v=19$m=19456,t=2,p=1$c29tZXNhbHRzb21lc2E$"
        "3vC8YQm3PjJmJjXKqTjFdFqpZ8sVQ0hZ1Xn0Q7wV9aE",
        "not-the-password",
    )
