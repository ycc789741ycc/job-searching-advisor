"""Envelope encryption for secrets at rest.

Each record gets its own AES-256-GCM data key, which is itself wrapped with the
process master key. Moving to a cloud KMS later replaces only ``_wrap``/
``_unwrap``; the stored format and the schema stay as they are
(docs/technical_boundaries.md section 4).

Importing this module is restricted by an import-linter contract: only
``kernel.ai_gateway`` and ``advisor.profile._infra.connectors`` may decrypt.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kernel.config import get_settings

_NONCE_BYTES = 12
_KEY_BYTES = 32
_FORMAT_VERSION = 1


class DecryptionError(RuntimeError):
    """Ciphertext could not be opened: wrong key, or the record was tampered with."""


@dataclass(frozen=True, slots=True)
class EncryptedBlob:
    """What gets written to the database. Opaque to everything but this module."""

    version: int
    wrapped_data_key: bytes
    key_nonce: bytes
    nonce: bytes
    ciphertext: bytes

    def to_storage(self) -> str:
        return json.dumps(
            {
                "v": self.version,
                "k": base64.b64encode(self.wrapped_data_key).decode(),
                "kn": base64.b64encode(self.key_nonce).decode(),
                "n": base64.b64encode(self.nonce).decode(),
                "c": base64.b64encode(self.ciphertext).decode(),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_storage(cls, raw: str) -> EncryptedBlob:
        try:
            data = json.loads(raw)
            return cls(
                version=int(data["v"]),
                wrapped_data_key=base64.b64decode(data["k"]),
                key_nonce=base64.b64decode(data["kn"]),
                nonce=base64.b64decode(data["n"]),
                ciphertext=base64.b64decode(data["c"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise DecryptionError("stored ciphertext is not a readable envelope") from exc


def _master_key() -> bytes:
    raw = get_settings().require_master_key().get_secret_value()
    key = base64.b64decode(raw)
    if len(key) != _KEY_BYTES:
        raise DecryptionError("MASTER_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def _wrap(data_key: bytes, aad: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(_NONCE_BYTES)
    wrapped = AESGCM(_master_key()).encrypt(nonce, data_key, aad)
    return wrapped, nonce


def _unwrap(wrapped: bytes, nonce: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(_master_key()).decrypt(nonce, wrapped, aad)
    except Exception as exc:  # cryptography raises InvalidTag
        raise DecryptionError("data key could not be unwrapped") from exc


def encrypt(plaintext: str, *, context: str) -> str:
    """Encrypt ``plaintext``, binding it to ``context`` (e.g. ``owner_id``).

    The context is authenticated, so a ciphertext copied onto another user's row
    will not open.
    """
    aad = context.encode()
    data_key = AESGCM.generate_key(bit_length=256)
    wrapped, key_nonce = _wrap(data_key, aad)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext.encode(), aad)
    return EncryptedBlob(_FORMAT_VERSION, wrapped, key_nonce, nonce, ciphertext).to_storage()


def decrypt(stored: str, *, context: str) -> str:
    """Open a ciphertext produced by :func:`encrypt`.

    The caller keeps the result in memory for the duration of one call and never
    logs it.
    """
    aad = context.encode()
    blob = EncryptedBlob.from_storage(stored)
    if blob.version != _FORMAT_VERSION:
        raise DecryptionError(f"unsupported envelope version {blob.version}")
    data_key = _unwrap(blob.wrapped_data_key, blob.key_nonce, aad)
    try:
        return AESGCM(data_key).decrypt(blob.nonce, blob.ciphertext, aad).decode()
    except Exception as exc:
        raise DecryptionError("ciphertext could not be opened") from exc


def last_four(secret: str) -> str:
    """What the client is allowed to see of a stored secret."""
    return secret[-4:] if len(secret) >= 4 else "*" * len(secret)
