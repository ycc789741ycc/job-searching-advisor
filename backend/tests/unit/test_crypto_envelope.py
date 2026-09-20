"""Envelope encryption: round-trips, and refuses to open what it should not."""

from __future__ import annotations

import base64

import pytest

from kernel.crypto import DecryptionError, decrypt, encrypt, last_four

OWNER = "11111111-1111-1111-1111-111111111111"
OTHER_OWNER = "22222222-2222-2222-2222-222222222222"


def test_round_trip(clean_env: None) -> None:
    stored = encrypt("sk-secret-key-value", context=OWNER)
    assert decrypt(stored, context=OWNER) == "sk-secret-key-value"


def test_ciphertext_does_not_contain_the_plaintext(clean_env: None) -> None:
    stored = encrypt("sk-secret-key-value", context=OWNER)
    assert "sk-secret-key-value" not in stored
    assert "sk-secret-key-value" not in base64.b64encode(stored.encode()).decode()


def test_every_record_gets_its_own_data_key(clean_env: None) -> None:
    first = encrypt("same-value", context=OWNER)
    second = encrypt("same-value", context=OWNER)
    assert first != second, "identical plaintexts must not produce identical ciphertexts"


def test_ciphertext_is_bound_to_its_owner(clean_env: None) -> None:
    """A row copied onto another user must not open."""
    stored = encrypt("sk-secret-key-value", context=OWNER)
    with pytest.raises(DecryptionError):
        decrypt(stored, context=OTHER_OWNER)


def test_tampered_ciphertext_is_rejected(clean_env: None) -> None:
    import json

    blob = json.loads(encrypt("sk-secret-key-value", context=OWNER))
    raw = bytearray(base64.b64decode(blob["c"]))
    raw[0] ^= 0xFF
    blob["c"] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(DecryptionError):
        decrypt(json.dumps(blob), context=OWNER)


def test_unreadable_envelope_is_rejected(clean_env: None) -> None:
    with pytest.raises(DecryptionError):
        decrypt("not-an-envelope", context=OWNER)


def test_short_master_key_is_rejected(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from kernel.config import get_settings

    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", base64.b64encode(b"short").decode())
    get_settings.cache_clear()
    with pytest.raises(DecryptionError, match="32 bytes"):
        encrypt("value", context=OWNER)


@pytest.mark.parametrize(
    ("secret", "expected"),
    [("sk-ant-abcd1234", "1234"), ("abc", "***"), ("", ""), ("1234", "1234")],
)
def test_last_four_is_all_the_client_ever_sees(secret: str, expected: str) -> None:
    assert last_four(secret) == expected
