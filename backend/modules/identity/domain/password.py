"""Password rules.

Pure policy, so it is testable without a database and without hashing anything.
The hashing itself is infrastructure and lives in ``infra/passwords.py``.

The rules follow current OWASP guidance rather than the older "one uppercase,
one digit, one symbol" style: length is what actually resists guessing, and
composition rules mostly push people toward `Password1!`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 200

# A small sample of what credential-stuffing lists try first.
#
# Every entry is at least MIN_PASSWORD_LENGTH characters: a shorter one could
# never match, because the length check runs first and would reject it with a
# different message. A real deployment should check a breach corpus instead;
# this is the floor, not the ceiling.
_OBVIOUS = frozenset(
    {
        "password1234",
        "passwordpassword",
        "password123456",
        "123456789012",
        "1234567890123",
        "qwerty123456",
        "qwertyuiopas",
        "letmein12345",
        "administrator",
        "iloveyou1234",
        "welcome12345",
        "trustno1trustno1",
    }
)


class WeakPasswordError(ValueError):
    """The password does not meet policy. The message is shown to the user."""


def assert_acceptable(password: str, *, email: str | None = None) -> None:
    """Reject what will obviously be guessed.

    Deliberately short: every extra rule is a rule a person works around.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. Length matters far "
            "more than punctuation."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        # Not a strength rule: unbounded input is a denial-of-service vector,
        # because hashing cost grows with length.
        raise WeakPasswordError(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    # Checked after length so the entries above are all reachable.
    if password.lower() in _OBVIOUS:
        raise WeakPasswordError("That password is one of the first ones guessed.")
    if email:
        local = email.split("@", 1)[0].lower()
        if local and len(local) >= 4 and local in password.lower():
            raise WeakPasswordError("Do not use your email address in your password.")


# --- brute-force resistance -------------------------------------------------

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class LockoutState:
    failed_attempts: int
    last_failed_at: datetime | None

    def is_locked(self, *, now: datetime) -> bool:
        """Locked once the attempts run out, until the window passes.

        Time-based rather than permanent: a permanent lock turns a guessing
        attempt against someone else into a way to lock them out of their own
        account.
        """
        if self.failed_attempts < MAX_FAILED_ATTEMPTS or self.last_failed_at is None:
            return False
        return now - self.last_failed_at < LOCKOUT_WINDOW

    def unlocks_at(self, *, now: datetime) -> datetime | None:
        if not self.is_locked(now=now) or self.last_failed_at is None:
            return None
        return self.last_failed_at + LOCKOUT_WINDOW

    def after_failure(self, *, now: datetime) -> LockoutState:
        # A failure after the window has passed starts the count again.
        expired = self.last_failed_at is not None and now - self.last_failed_at >= LOCKOUT_WINDOW
        base = 0 if expired else self.failed_attempts
        return LockoutState(failed_attempts=base + 1, last_failed_at=now)

    def after_success(self) -> LockoutState:
        return LockoutState(failed_attempts=0, last_failed_at=None)


def normalize_email(email: str) -> str:
    """One account per address, however it was typed."""
    return email.strip().lower()
