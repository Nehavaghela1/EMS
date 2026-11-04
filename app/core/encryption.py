"""AES-256-GCM field encryption (Spec 9.6).

Blob layout:  version (1 byte) || nonce (12 bytes) || ciphertext || tag (16 bytes)

The version byte picks the key, so a rotated key can still read old blobs. The associated
data binds the version byte, the company id and the column name: a blob copied to another
company's row or to another column fails authentication instead of decrypting.

Nothing here ever puts a key or a plaintext value into an exception message or a log line.
"""

import base64
import binascii
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.exceptions import AppError

NONCE_BYTES = 12
KEY_BYTES = 32
TAG_BYTES = 16
_HEADER_BYTES = 1 + NONCE_BYTES


class EncryptionUnavailableError(AppError):
    """No usable key is configured: a server setting problem, not a client mistake."""

    status_code = 503
    code = "encryption_unavailable"


class DecryptionFailedError(AppError):
    """A stored blob is damaged, was copied from another row or column, or has a key version
    nobody can read. The message never carries the value."""

    status_code = 500
    code = "decryption_failed"


def _decode_key(raw: str | None, setting_name: str) -> bytes:
    if raw is None or not raw.strip():
        raise EncryptionUnavailableError(
            f"{setting_name} is not set; this value cannot be saved or read until it is."
        )
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != KEY_BYTES:
        raise EncryptionUnavailableError(
            f"{setting_name} must be the base64 text of exactly {KEY_BYTES} random bytes."
        )
    return key


def _current_version() -> int:
    version = settings.ENCRYPTION_KEY_VERSION
    if not 1 <= version <= 255:
        raise EncryptionUnavailableError("ENCRYPTION_KEY_VERSION must be between 1 and 255.")
    return version


def _key_for_version(version: int) -> bytes:
    if version == _current_version():
        return _decode_key(settings.ENCRYPTION_KEY, "ENCRYPTION_KEY")
    previous = settings.ENCRYPTION_PREVIOUS_KEYS.get(version)
    if previous is None:
        raise DecryptionFailedError(
            f"The stored value was encrypted with key version {version}, which is not available."
        )
    return _decode_key(previous, "ENCRYPTION_PREVIOUS_KEYS")


def _associated_data(version: int, company_id: uuid.UUID, column: str) -> bytes:
    return bytes([version]) + f"{company_id}|{column}".encode()


def encrypt_field(plaintext: str, *, company_id: uuid.UUID, column: str) -> bytes:
    version = _current_version()
    key = _decode_key(settings.ENCRYPTION_KEY, "ENCRYPTION_KEY")
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(key).encrypt(
        nonce, plaintext.encode(), _associated_data(version, company_id, column)
    )
    return bytes([version]) + nonce + sealed


def decrypt_field(blob: bytes, *, company_id: uuid.UUID, column: str) -> str:
    if len(blob) < _HEADER_BYTES + TAG_BYTES:
        raise DecryptionFailedError("The stored value is damaged and cannot be read.")
    version = blob[0]
    key = _key_for_version(version)
    nonce = blob[1:_HEADER_BYTES]
    try:
        plain = AESGCM(key).decrypt(
            nonce, blob[_HEADER_BYTES:], _associated_data(version, company_id, column)
        )
    except InvalidTag:
        raise DecryptionFailedError(
            "The stored value failed its integrity check and cannot be read."
        ) from None
    return plain.decode()
