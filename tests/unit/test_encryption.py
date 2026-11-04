"""Unit tests for app/core/encryption.py (Spec 9.6, 5.7 rules 3 and 8)."""

import base64
import uuid

import pytest

from app.core.config import settings
from app.core.encryption import (
    DecryptionFailedError,
    EncryptionUnavailableError,
    decrypt_field,
    encrypt_field,
)

COMPANY = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_COMPANY = uuid.UUID("22222222-2222-2222-2222-222222222222")
COLUMN = "payout_account_number"
PLAIN = "123456789012"


def _key(seed: int) -> str:
    return base64.b64encode(bytes([seed]) * 32).decode()


def test_round_trip_gives_back_the_same_text() -> None:
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert decrypt_field(blob, company_id=COMPANY, column=COLUMN) == PLAIN, "round trip broke"


def test_the_blob_never_contains_the_plain_text() -> None:
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert PLAIN.encode() not in blob, "the plain number is visible inside the blob"


def test_layout_is_version_byte_then_12_byte_nonce_then_ciphertext_and_16_byte_tag() -> None:
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert blob[0] == settings.ENCRYPTION_KEY_VERSION, "first byte must be the key version"
    assert len(blob) == 1 + 12 + len(PLAIN) + 16, f"blob layout wrong, length {len(blob)}"


def test_every_call_uses_a_fresh_nonce() -> None:
    blobs = [encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN) for _ in range(20)]
    nonces = {b[1:13] for b in blobs}
    assert len(nonces) == 20, "a nonce was reused"
    assert len(set(blobs)) == 20, "the same plain text gave the same blob twice"


def test_a_flipped_byte_in_the_ciphertext_fails() -> None:
    blob = bytearray(encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN))
    blob[14] ^= 0x01
    with pytest.raises(DecryptionFailedError):
        decrypt_field(bytes(blob), company_id=COMPANY, column=COLUMN)


def test_a_flipped_byte_in_the_tag_fails() -> None:
    blob = bytearray(encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionFailedError):
        decrypt_field(bytes(blob), company_id=COMPANY, column=COLUMN)


def test_a_flipped_nonce_byte_fails() -> None:
    blob = bytearray(encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN))
    blob[2] ^= 0x01
    with pytest.raises(DecryptionFailedError):
        decrypt_field(bytes(blob), company_id=COMPANY, column=COLUMN)


def test_a_blob_copied_to_another_company_fails() -> None:
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    with pytest.raises(DecryptionFailedError):
        decrypt_field(blob, company_id=OTHER_COMPANY, column=COLUMN)


def test_a_blob_copied_to_another_column_fails() -> None:
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    with pytest.raises(DecryptionFailedError):
        decrypt_field(blob, company_id=COMPANY, column="some_other_column")


@pytest.mark.parametrize("blob", [b"", b"\x01", b"\x01" + b"\x00" * 20])
def test_a_truncated_blob_fails_clearly(blob: bytes) -> None:
    with pytest.raises(DecryptionFailedError):
        decrypt_field(blob, company_id=COMPANY, column=COLUMN)


def test_the_error_message_never_carries_the_value_or_the_key() -> None:
    blob = bytearray(encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionFailedError) as caught:
        decrypt_field(bytes(blob), company_id=COMPANY, column=COLUMN)
    text = str(caught.value)
    assert PLAIN not in text and (settings.ENCRYPTION_KEY or "") not in text, text


def test_a_decryption_failure_is_a_controlled_500() -> None:
    assert DecryptionFailedError.status_code == 500, "a damaged blob must be a controlled 500"


def test_without_a_key_encrypting_is_refused_with_a_503_class_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", None)
    with pytest.raises(EncryptionUnavailableError) as caught:
        encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert caught.value.status_code == 503, "a missing key must be 503"


def test_an_empty_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    with pytest.raises(EncryptionUnavailableError):
        encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)


def test_without_a_key_decrypting_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", None)
    with pytest.raises(EncryptionUnavailableError):
        decrypt_field(blob, company_id=COMPANY, column=COLUMN)


@pytest.mark.parametrize(
    "bad",
    [
        "not base64 !!",
        base64.b64encode(b"short").decode(),
        base64.b64encode(bytes(31)).decode(),
        base64.b64encode(bytes(33)).decode(),
    ],
)
def test_a_key_that_is_not_exactly_32_bytes_fails_and_is_never_printed(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", bad)
    with pytest.raises(EncryptionUnavailableError) as caught:
        encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert bad not in str(caught.value), "the bad key was printed in the error"
    assert "32" in str(caught.value), "the error must say what a good key looks like"


def test_the_version_setting_is_written_into_the_version_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 7)
    blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert blob[0] == 7, "the version setting did not reach the version byte"
    assert decrypt_field(blob, company_id=COMPANY, column=COLUMN) == PLAIN


@pytest.mark.parametrize("version", [0, 256, -1])
def test_a_version_outside_one_byte_is_refused(
    monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", version)
    with pytest.raises(EncryptionUnavailableError):
        encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)


def test_after_a_rotation_an_old_blob_is_read_with_the_previous_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", _key(1))
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 1)
    old_blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", _key(2))
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 2)
    monkeypatch.setattr(settings, "ENCRYPTION_PREVIOUS_KEYS", {1: _key(1)})

    assert decrypt_field(old_blob, company_id=COMPANY, column=COLUMN) == PLAIN
    new_blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)
    assert new_blob[0] == 2, "new writes must use the new version"
    assert decrypt_field(new_blob, company_id=COMPANY, column=COLUMN) == PLAIN


def test_after_a_rotation_without_the_previous_key_the_old_blob_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", _key(1))
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 1)
    old_blob = encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN)

    monkeypatch.setattr(settings, "ENCRYPTION_KEY", _key(2))
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 2)
    monkeypatch.setattr(settings, "ENCRYPTION_PREVIOUS_KEYS", {})
    with pytest.raises(DecryptionFailedError) as caught:
        decrypt_field(old_blob, company_id=COMPANY, column=COLUMN)
    assert "version 1" in str(caught.value), "the error must name the unknown key version"


def test_a_blob_with_an_unknown_version_fails_clearly() -> None:
    blob = bytearray(encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN))
    blob[0] = 99
    with pytest.raises(DecryptionFailedError) as caught:
        decrypt_field(bytes(blob), company_id=COMPANY, column=COLUMN)
    assert "version 99" in str(caught.value), "the error must name the unknown key version"


def test_the_version_byte_is_authenticated_not_just_used_to_pick_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same key under two version numbers: relabelling the blob must still fail."""
    monkeypatch.setattr(settings, "ENCRYPTION_PREVIOUS_KEYS", {2: settings.ENCRYPTION_KEY or ""})
    blob = bytearray(encrypt_field(PLAIN, company_id=COMPANY, column=COLUMN))
    blob[0] = 2
    with pytest.raises(DecryptionFailedError):
        decrypt_field(bytes(blob), company_id=COMPANY, column=COLUMN)
