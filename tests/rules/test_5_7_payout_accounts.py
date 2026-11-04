"""Module 5, sub-feature 5.7: Payout accounts. One test per rule line (R1..R10).

The company payout settings (bank name, account number, IFSC, enabled flag) live on the
statutory config row. The account number is encrypted at rest (AES-256-GCM, app/core/encryption)
and every API surface shows it as eight asterisks plus the last four digits.
The encryption helper itself is tested in tests/unit/test_encryption.py.
"""

import base64
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.encryption import decrypt_field, encrypt_field
from app.core.rate_limit import limiter
from app.core.security import decode_access_token
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import StatutoryConfig
from app.modules.payroll.schemas import StatutoryConfigUpdateRequest
from app.modules.payroll.service import StatutoryConfigService
from app.modules.platform.models import AuditLog
from app.modules.platform.service import AuditService
from tests.conftest import REPO_ROOT, TEST_ENCRYPTION_KEY, TenantContext, _make_user_headers
from tests.rules.test_5_4_payroll_runs import _extra_user

URL = "/api/v1/payroll/statutory-config"
ACCOUNT = "123456789012"
LAST4 = "9012"
MASKED = "********9012"
BANK = "HDFC Bank"
IFSC = "HDFC0001234"
COLUMN = "payout_account_number"
FULL = {
    "payout_bank_name": BANK,
    "payout_account_number": ACCOUNT,
    "payout_ifsc_code": IFSC,
}
PAYOUT_FIELDS = ("payout_bank_name", "payout_account_number", "payout_ifsc_code", "payout_enabled")
MIGRATION_REVISION = "685f8636a5ca"


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


# ---------------------------------------------------------------- helpers


def _put(client: TestClient, headers: dict[str, str], body: dict[str, Any]):
    return client.put(URL, json=body, headers=headers)


def _get(client: TestClient, headers: dict[str, str], query: str = ""):
    return client.get(f"{URL}{query}", headers=headers)


def _saved(client: TestClient, headers: dict[str, str]) -> None:
    resp = _put(client, headers, FULL)
    assert resp.status_code == 200, resp.text


def _expect_new_columns(db: Session) -> None:
    names = {c["name"] for c in inspect(db.get_bind()).get_columns("statutory_configs")}
    assert {"payout_account_number_enc", "payout_account_last4"} <= names, (
        "R3: the table needs payout_account_number_enc and payout_account_last4"
    )


def _row(db: Session, cid: uuid.UUID):
    """The raw row, read with plain SQL: what is really in the table."""
    _expect_new_columns(db)
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)
    db.expire_all()
    return (
        db.execute(text("SELECT * FROM statutory_configs WHERE company_id = :c"), {"c": cid})
        .mappings()
        .first()
    )


def _audit(db: Session, cid: uuid.UUID, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)
    return db.query(AuditLog).filter(AuditLog.company_id == cid, AuditLog.action == action).all()


def _company_of(headers: dict[str, str]) -> uuid.UUID:
    token = headers["Authorization"].split(" ", 1)[1]
    return uuid.UUID(decode_access_token(token)["company_id"])


def _owner(db: Session, ctx: TenantContext) -> dict[str, str]:
    return _make_user_headers(db, ctx.company_id, UserRole.owner)


def _blob(db: Session, cid: uuid.UUID) -> bytes:
    row = _row(db, cid)
    assert row is not None and row["payout_account_number_enc"] is not None
    return bytes(row["payout_account_number_enc"])


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401(client: TestClient) -> None:
    codes = [
        client.get(URL).status_code,
        client.put(URL, json={"pt_state": "Gujarat"}).status_code,
        client.get(f"{URL}?reveal=true").status_code,
    ]
    assert codes == [401] * 3, f"R1: no login must give 401 on every payout route, got {codes}"


@pytest.mark.parametrize("who", ["employee_headers", "manager_headers"])
def test_R1_employee_and_manager_get_403_on_read_change_and_reveal(
    client: TestClient, company_a: TenantContext, who: str
) -> None:
    h = getattr(company_a, who)
    codes = [
        _get(client, h).status_code,
        _put(client, h, FULL).status_code,
        _get(client, h, "?reveal=true").status_code,
    ]
    assert codes == [403] * 3, f"R1: {who} must get 403 on read, change and reveal: {codes}"


def test_R1_hr_admin_and_owner_can_read_and_change(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    owner = _owner(db, company_a)
    assert _put(client, company_a.hr_headers, FULL).status_code == 200, "R1: hr_admin must change"
    seen = _get(client, owner)
    assert seen.status_code == 200, f"R1: owner must read: {seen.text}"
    assert seen.json()["payout_bank_name"] == BANK, "R1: owner must see the saved bank name"
    assert _put(client, owner, {"payout_bank_name": "ICICI Bank"}).status_code == 200, (
        "R1: owner must change"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"payout_bank_name": BANK},
        {"payout_account_number": ACCOUNT},
        {"payout_ifsc_code": IFSC},
        {"payout_enabled": False},
    ],
)
def test_R1_super_admin_gets_403_when_changing_a_payout_field(
    client: TestClient, db: Session, super_admin_headers: dict[str, str], body: dict[str, Any]
) -> None:
    resp = _put(client, super_admin_headers, body)
    assert resp.status_code == 403, f"R1: super_admin changing {body} must give 403: {resp.text}"
    row = _row(db, _company_of(super_admin_headers))
    if row is not None:
        assert row["payout_bank_name"] is None and row["payout_account_number_enc"] is None, (
            "R1: a refused super_admin change must save nothing"
        )


def test_R1_super_admin_gets_403_on_reveal_and_no_audit_row(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    resp = _get(client, super_admin_headers, "?reveal=true")
    assert resp.status_code == 403, f"R1: super_admin reveal must give 403: {resp.text}"
    assert _audit(db, _company_of(super_admin_headers), "PAYOUT_ACCOUNT_REVEALED") == [], (
        "R1: a refused reveal must not write a reveal audit row"
    )


def test_R1_super_admin_still_reads_and_changes_the_other_settings_but_never_sees_payout(
    client: TestClient, db: Session, super_admin_headers: dict[str, str]
) -> None:
    _expect_new_columns(db)
    cid = _company_of(super_admin_headers)
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)
    first = _get(client, super_admin_headers)  # makes the config row
    assert first.status_code == 200, f"R1: super_admin keeps the non-payout read: {first.text}"
    db.execute(
        text(
            "UPDATE statutory_configs SET payout_bank_name = 'Secret Bank', "
            "payout_ifsc_code = 'SECR0000001', payout_enabled = true, "
            "payout_account_number_enc = :enc, payout_account_last4 = '9012' "
            "WHERE company_id = :c"
        ),
        {"enc": encrypt_field(ACCOUNT, company_id=cid, column=COLUMN), "c": cid},
    )
    db.commit()
    shown = _get(client, super_admin_headers).json()
    assert shown["pf_enabled"] is True, "R1: the non-payout settings must still be readable"
    assert shown["payout_bank_name"] is None, "R1: super_admin must not see the bank name"
    assert shown["payout_account_number"] is None, "R1: super_admin must not see the number"
    assert shown["payout_ifsc_code"] is None, "R1: super_admin must not see the IFSC"
    assert shown["payout_enabled"] is False, "R1: super_admin must not see the enabled flag"
    changed = _put(client, super_admin_headers, {"pt_state": "Gujarat"})
    assert changed.status_code == 200, f"R1: non-payout change keeps its role: {changed.text}"
    assert changed.json()["payout_account_number"] is None, "R1: PUT must hide payout too"


def test_R1_another_companys_payout_data_is_never_shown(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    theirs = _get(client, company_b.hr_headers)
    assert theirs.status_code == 200
    body = theirs.json()
    assert body["payout_bank_name"] is None and body["payout_account_number"] is None, (
        "R1: company B must not see company A's payout settings"
    )
    assert body["payout_ifsc_code"] is None, "R1: company B must not see company A's IFSC"
    assert ACCOUNT not in theirs.text and MASKED not in theirs.text, "R1: A's number leaked to B"
    revealed = _get(client, company_b.hr_headers, "?reveal=true")
    assert ACCOUNT not in revealed.text, "R1: A's number revealed to B"


def test_R1_row_level_security_hides_the_encrypted_column_from_another_company(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    _expect_new_columns(db)
    bind_tenant_to_session(db, company_id=company_b.company_id, is_platform_admin=False)
    rows = db.execute(
        text("SELECT payout_account_number_enc FROM statutory_configs WHERE company_id = :a"),
        {"a": company_a.company_id},
    ).fetchall()
    assert rows == [], "R1: company B can read company A's encrypted number through SQL"


# ------------------------------------------------------------------- R2


def test_R2_bank_name_is_trimmed_and_must_be_1_to_100_characters(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    ok = _put(client, company_a.hr_headers, {"payout_bank_name": "  HDFC Bank  "})
    assert ok.status_code == 200 and ok.json()["payout_bank_name"] == "HDFC Bank", (
        f"R2: bank name must be trimmed: {ok.text}"
    )
    for bad in ("", "   ", "x" * 101):
        resp = _put(client, company_a.hr_headers, {"payout_bank_name": bad})
        assert resp.status_code == 422, f"R2: bank name {bad[:5]!r}.. must give 422: {resp.text}"
    assert _put(client, company_a.hr_headers, {"payout_bank_name": "x" * 100}).status_code == 200, (
        "R2: 100 characters is allowed"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "12345678",
        "1234567890123456789",
        "12345abc9012",
        "1234 5678 9012",
        "-12345678901",
        "1234.5678901",
        "١٢٣٤٥٦٧٨٩",
    ],
)
def test_R2_account_number_must_be_9_to_18_ascii_digits(
    client: TestClient, db: Session, company_a: TenantContext, bad: str
) -> None:
    resp = _put(client, company_a.hr_headers, {"payout_account_number": bad})
    assert resp.status_code == 422, f"R2: account number {bad!r} must give 422: {resp.text}"
    assert bad not in resp.text, "R2: the 422 must not echo the submitted account number"
    row = _row(db, company_a.company_id)
    assert row is None or row["payout_account_number_enc"] is None, (
        "R2: a bad account number reached the database"
    )


@pytest.mark.parametrize("good", ["123456789", "123456789012345678"])
def test_R2_the_account_number_length_limits_are_inclusive(
    client: TestClient, company_a: TenantContext, good: str
) -> None:
    resp = _put(client, company_a.hr_headers, {"payout_account_number": good})
    assert resp.status_code == 200, f"R2: {len(good)} digits must be accepted: {resp.text}"


def test_R2_ifsc_is_upper_cased_and_must_match_the_pattern(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    ok = _put(client, company_a.hr_headers, {"payout_ifsc_code": "hdfc0001234"})
    assert ok.status_code == 200 and ok.json()["payout_ifsc_code"] == "HDFC0001234", (
        f"R2: IFSC must be upper-cased: {ok.text}"
    )
    assert _row(db, company_a.company_id)["payout_ifsc_code"] == "HDFC0001234", (
        "R2: the upper-cased IFSC must be what is stored"
    )
    for bad in ("HDFC1001234", "HDF00001234", "HDFC000123", "HDFC00012345", "HDFC0001-34", ""):
        resp = _put(client, company_a.hr_headers, {"payout_ifsc_code": bad})
        assert resp.status_code == 422, f"R2: IFSC {bad!r} must give 422: {resp.text}"
    assert _row(db, company_a.company_id)["payout_ifsc_code"] == "HDFC0001234", (
        "R2: a bad IFSC reached the database"
    )


def test_R2_enabled_can_be_set_true_only_when_all_three_are_present(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    nothing = _put(client, company_a.hr_headers, {"payout_enabled": True})
    assert nothing.status_code == 422, (
        f"R2: enabling with nothing set must give 422: {nothing.text}"
    )
    _put(client, company_a.hr_headers, {"payout_bank_name": BANK, "payout_ifsc_code": IFSC})
    no_number = _put(client, company_a.hr_headers, {"payout_enabled": True})
    assert no_number.status_code == 422, f"R2: enabling without a number: {no_number.text}"
    assert _row(db, company_a.company_id)["payout_enabled"] is False, "R2: flag must stay false"
    both = _put(
        client, company_a.hr_headers, {"payout_account_number": ACCOUNT, "payout_enabled": True}
    )
    assert both.status_code == 200 and both.json()["payout_enabled"] is True, (
        f"R2: enabling together with the last missing field must work: {both.text}"
    )


def test_R2_a_complete_set_can_be_enabled_in_one_request(
    client: TestClient, company_a: TenantContext
) -> None:
    resp = _put(client, company_a.hr_headers, {**FULL, "payout_enabled": True})
    assert resp.status_code == 200 and resp.json()["payout_enabled"] is True, resp.text


def test_R2_removing_a_required_value_while_enabled_is_refused(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _put(client, company_a.hr_headers, {**FULL, "payout_enabled": True})
    resp = _put(client, company_a.hr_headers, {"payout_ifsc_code": None})
    assert resp.status_code == 422, (
        f"R2: clearing the IFSC while enabled must give 422: {resp.text}"
    )
    assert _row(db, company_a.company_id)["payout_ifsc_code"] == IFSC, "R2: IFSC must be kept"
    off = _put(client, company_a.hr_headers, {"payout_enabled": False, "payout_ifsc_code": None})
    assert off.status_code == 200, f"R2: disabling and clearing together is fine: {off.text}"


def test_R2_enabled_null_gives_422(client: TestClient, company_a: TenantContext) -> None:
    resp = _put(client, company_a.hr_headers, {"payout_enabled": None})
    assert resp.status_code == 422, f"R2: payout_enabled null must give 422: {resp.text}"


@pytest.mark.parametrize(
    "body", [{"payout_bogus": "x"}, {"nonsense": 1}, {"payout_account_number_enc": "abc"}]
)
def test_R2_unknown_fields_give_422(
    client: TestClient, company_a: TenantContext, body: dict[str, Any]
) -> None:
    resp = _put(client, company_a.hr_headers, body)
    assert resp.status_code == 422, f"R2: unknown field {body} must give 422: {resp.text}"


# ------------------------------------------------------------------- R3


def test_R3_the_table_has_no_plain_number_column_only_blob_and_last4(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    names = {c["name"] for c in inspect(db.get_bind()).get_columns("statutory_configs")}
    assert "payout_account_number" not in names, "R3: the plain column must be removed"
    assert {"payout_account_number_enc", "payout_account_last4"} <= names, (
        f"R3: blob and last4 columns missing: {sorted(names)}"
    )
    assert not hasattr(StatutoryConfig, "payout_account_number"), (
        "R3: the model must not carry a plain number attribute"
    )


def test_R3_a_raw_sql_read_never_shows_the_plain_number(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    row = _row(db, company_a.company_id)
    assert row is not None
    for column, value in row.items():
        text_value = (
            bytes(value).decode("latin-1") if isinstance(value, (bytes, memoryview)) else str(value)
        )
        assert ACCOUNT not in text_value, f"R3: the plain number is visible in column {column}"
    assert row["payout_account_last4"] == LAST4, "R3: last4 must sit beside the blob"
    assert isinstance(row["payout_account_number_enc"], (bytes, memoryview)), "R3: blob is bytes"


def test_R3_the_blob_is_version_nonce_ciphertext_and_decrypts_with_company_and_column(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    blob = _blob(db, company_a.company_id)
    assert blob[0] == settings.ENCRYPTION_KEY_VERSION, "R3: first byte must be the key version"
    assert len(blob) == 1 + 12 + len(ACCOUNT) + 16, f"R3: blob layout wrong, length {len(blob)}"
    plain = decrypt_field(blob, company_id=company_a.company_id, column=COLUMN)
    assert plain == ACCOUNT, "R3: the blob must decrypt to the saved number"


def test_R3_every_save_writes_a_fresh_nonce(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    first = _blob(db, company_a.company_id)
    _put(client, company_a.hr_headers, {"payout_account_number": "999988887777"})
    _put(client, company_a.hr_headers, {"payout_account_number": ACCOUNT})
    third = _blob(db, company_a.company_id)
    assert first[1:13] != third[1:13], "R3: the nonce was reused for a new save"


def test_R3_a_tampered_blob_gives_a_controlled_500_without_the_value(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    bad = bytearray(_blob(db, company_a.company_id))
    bad[-1] ^= 0x01
    db.execute(
        text("UPDATE statutory_configs SET payout_account_number_enc = :b WHERE company_id = :c"),
        {"b": bytes(bad), "c": company_a.company_id},
    )
    db.commit()
    resp = _get(client, company_a.hr_headers, "?reveal=true")
    assert resp.status_code == 500, f"R3: a tampered blob must give a 500: {resp.status_code}"
    body = resp.json()
    assert body["error"]["code"] == "decryption_failed", f"R3: controlled error code: {body}"
    assert "Traceback" not in resp.text and ACCOUNT not in resp.text, "R3: leak in the 500"
    assert _audit(db, company_a.company_id, "PAYOUT_ACCOUNT_REVEALED") == [], (
        "R3: nothing was revealed, so no reveal audit row"
    )
    masked = _get(client, company_a.hr_headers)
    assert masked.status_code == 200 and masked.json()["payout_account_number"] == MASKED, (
        "R3: the masked view uses last4 only and must still work"
    )


def test_R3_a_blob_copied_from_another_company_fails(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    _saved(client, company_b.hr_headers)
    a_blob = _blob(db, company_a.company_id)
    bind_tenant_to_session(db, company_id=company_b.company_id, is_platform_admin=False)
    db.execute(
        text("UPDATE statutory_configs SET payout_account_number_enc = :b WHERE company_id = :c"),
        {"b": a_blob, "c": company_b.company_id},
    )
    db.commit()
    resp = _get(client, company_b.hr_headers, "?reveal=true")
    assert resp.status_code == 500, f"R3: a copied blob must not decrypt: {resp.status_code}"
    assert ACCOUNT not in resp.text, "R3: a copied blob leaked the number"


def test_R3_the_same_number_in_two_companies_gives_different_blobs(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    _saved(client, company_b.hr_headers)
    assert _blob(db, company_a.company_id) != _blob(db, company_b.company_id), (
        "R3: identical blobs for the same number"
    )


# ------------------------------------------------------------------- R4


def _cfg() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _previous_revision() -> str:
    revision = ScriptDirectory.from_config(_cfg()).get_revision(MIGRATION_REVISION)
    assert revision is not None and isinstance(revision.down_revision, str)
    return revision.down_revision


def _owner_engine():
    assert settings.TEST_MIGRATION_URL is not None
    return create_engine(settings.TEST_MIGRATION_URL)


def _insert_plain_config(engine, cid: uuid.UUID, plain: str | None) -> None:
    """A company and a statutory config row that still holds a plain number, written the way
    the old schema stored it (raw SQL: the old column is not on the current model)."""
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        conn.execute(
            text(
                "INSERT INTO companies (id, name, code, email, status, country, currency, "
                "last_employee_seq, created_at, updated_at) VALUES (:c, 'Payout Mig Co', :code, "
                ":email, 'active', 'IN', 'INR', 0, now(), now())"
            ),
            {
                "c": cid,
                "code": f"PMC{cid.hex[:5].upper()}",
                "email": f"pmc-{cid.hex[:6]}@example.test",
            },
        )
        conn.execute(
            text(
                "INSERT INTO statutory_configs (id, company_id, country, pf_enabled, "
                "pf_employee_rate, pf_employer_rate, pf_wage_ceiling, pf_restrict_to_ceiling, "
                "esi_enabled, esi_employee_rate, esi_employer_rate, esi_wage_ceiling, "
                "pt_enabled, lwf_enabled, tds_enabled, default_tax_regime, payout_enabled, "
                "payout_account_number) VALUES (:id, :c, 'IN', true, 12, 12, 15000, true, true, "
                "0.75, 3.25, 21000, true, false, true, 'new', false, :plain)"
            ),
            {"id": uuid.uuid4(), "c": cid, "plain": plain},
        )


def _purge_company(engine, cid: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        conn.execute(text("DELETE FROM statutory_configs WHERE company_id = :c"), {"c": cid})
        conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})


def _columns(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("statutory_configs")}


def test_R4_upgrade_encrypts_a_plain_number_and_downgrade_restores_it() -> None:
    cid = uuid.uuid4()
    engine = _owner_engine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        command.downgrade(cfg, _previous_revision())
        try:
            _insert_plain_config(engine, cid, ACCOUNT)
            command.upgrade(cfg, MIGRATION_REVISION)
            names = _columns(engine)
            assert "payout_account_number" not in names, "R4: the plain column must be gone"
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                row = conn.execute(
                    text(
                        "SELECT payout_account_number_enc, payout_account_last4 "
                        "FROM statutory_configs WHERE company_id = :c"
                    ),
                    {"c": cid},
                ).one()
            assert row[1] == LAST4, f"R4: last4 must be stored, got {row[1]!r}"
            assert ACCOUNT.encode() not in bytes(row[0]), "R4: the blob holds the plain number"
            assert decrypt_field(bytes(row[0]), company_id=cid, column=COLUMN) == ACCOUNT, (
                "R4: the migrated blob must decrypt to the old number"
            )

            command.downgrade(cfg, _previous_revision())
            assert "payout_account_number" in _columns(engine), "R4: downgrade restores the column"
            assert "payout_account_number_enc" not in _columns(engine)
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                plain = conn.execute(
                    text("SELECT payout_account_number FROM statutory_configs WHERE company_id=:c"),
                    {"c": cid},
                ).scalar_one()
            assert plain == ACCOUNT, "R4: downgrade must decrypt the number back"
        finally:
            _purge_company(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R4_a_plain_number_without_a_key_makes_the_migration_fail_clearly_and_change_nothing() -> (
    None
):
    cid = uuid.uuid4()
    engine = _owner_engine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        command.downgrade(cfg, _previous_revision())
        try:
            _insert_plain_config(engine, cid, ACCOUNT)
            mp.setattr(settings, "ENCRYPTION_KEY", None)
            with pytest.raises(RuntimeError) as caught:
                command.upgrade(cfg, MIGRATION_REVISION)
            message = str(caught.value)
            assert "ENCRYPTION_KEY" in message, f"R4: the failure must name the setting: {message}"
            assert ACCOUNT not in message, "R4: the failure message printed the number"
            names = _columns(engine)
            assert "payout_account_number" in names and "payout_account_number_enc" not in names, (
                f"R4: a failed migration must change nothing: {sorted(names)}"
            )
        finally:
            mp.setattr(settings, "ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
            _purge_company(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R4_an_empty_table_migrates_both_ways_without_a_key() -> None:
    engine = _owner_engine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        command.downgrade(cfg, _previous_revision())
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                conn.execute(text("DELETE FROM statutory_configs"))
            mp.setattr(settings, "ENCRYPTION_KEY", None)
            command.upgrade(cfg, MIGRATION_REVISION)
            names = _columns(engine)
            assert "payout_account_number" not in names, "R4: empty table: column not removed"
            assert {"payout_account_number_enc", "payout_account_last4"} <= names, (
                "R4: empty table: new columns missing"
            )
            command.downgrade(cfg, _previous_revision())
            assert "payout_account_number" in _columns(engine), "R4: empty table: no downgrade"
        finally:
            mp.setattr(settings, "ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R4_a_row_without_a_number_migrates_to_nulls_and_needs_no_key() -> None:
    cid = uuid.uuid4()
    engine = _owner_engine()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        command.downgrade(cfg, _previous_revision())
        try:
            _insert_plain_config(engine, cid, None)
            mp.setattr(settings, "ENCRYPTION_KEY", None)
            command.upgrade(cfg, MIGRATION_REVISION)
            assert {"payout_account_number_enc", "payout_account_last4"} <= _columns(engine), (
                "R4: the migration must add the blob and last4 columns"
            )
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                row = conn.execute(
                    text(
                        "SELECT payout_account_number_enc, payout_account_last4 "
                        "FROM statutory_configs WHERE company_id = :c"
                    ),
                    {"c": cid},
                ).one()
            assert row[0] is None and row[1] is None, f"R4: no number must stay null: {row}"
        finally:
            mp.setattr(settings, "ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
            _purge_company(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R4_the_models_and_the_migrations_agree_on_statutory_configs() -> None:
    """What `alembic check` does in CI, for the table this package changed."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.base import Base

    engine = _owner_engine()
    try:
        with engine.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    mine = [d for d in diffs if "statutory_configs" in str(d)]
    assert mine == [], f"R4: models and migrations differ: {mine}"


# ------------------------------------------------------------------- R5


def test_R5_put_and_get_show_eight_asterisks_plus_the_last_four(
    client: TestClient, company_a: TenantContext
) -> None:
    put = _put(client, company_a.hr_headers, FULL)
    assert put.json()["payout_account_number"] == MASKED, f"R5: PUT masking: {put.text}"
    get = _get(client, company_a.hr_headers)
    assert get.json()["payout_account_number"] == MASKED, f"R5: GET masking: {get.text}"
    assert put.json()["payout_account_number"] == get.json()["payout_account_number"], (
        "R5: GET and PUT must use the same masking"
    )


@pytest.mark.parametrize("number", ["123456789", "123456789012345678"])
def test_R5_the_mask_is_always_eight_asterisks_whatever_the_length(
    client: TestClient, company_a: TenantContext, number: str
) -> None:
    resp = _put(client, company_a.hr_headers, {"payout_account_number": number})
    assert resp.json()["payout_account_number"] == "********" + number[-4:], resp.text


def test_R5_no_response_field_carries_the_blob_or_the_plain_number(
    client: TestClient, company_a: TenantContext
) -> None:
    put = _put(client, company_a.hr_headers, FULL)
    get = _get(client, company_a.hr_headers)
    for resp in (put, get):
        assert ACCOUNT not in resp.text, "R5: the plain number is in a response"
        keys = set(resp.json())
        assert "payout_account_number_enc" not in keys, "R5: the blob field is in a response"
        assert "payout_account_last4" not in keys, "R5: the last4 field is in a response"


def test_R5_no_number_stored_shows_null(client: TestClient, company_a: TenantContext) -> None:
    assert _get(client, company_a.hr_headers).json()["payout_account_number"] is None


def test_R5_audit_rows_never_hold_the_number_or_its_mask(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    _put(client, company_a.hr_headers, {"payout_account_number": "999988887777"})
    _get(client, company_a.hr_headers, "?reveal=true")
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    rows = db.query(AuditLog).filter(AuditLog.company_id == company_a.company_id).all()
    assert rows, "R5: expected audit rows"
    for row in rows:
        shown = f"{row.details} {row.entity_type} {row.action}"
        for secret in (ACCOUNT, "999988887777", MASKED, "********7777"):
            assert secret not in shown, f"R5: audit row {row.action} holds {secret}"


def test_R5_logs_never_hold_the_number(
    client: TestClient, company_a: TenantContext, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _saved(client, company_a.hr_headers)
    _get(client, company_a.hr_headers, "?reveal=true")
    _put(client, company_a.hr_headers, {"payout_account_number": "12345"})  # a refused value
    assert ACCOUNT not in caplog.text, "R5: the account number reached a log line"
    assert "12345" not in caplog.text.replace("123456789012", ""), "R5: refused value was logged"


def test_R5_error_responses_never_echo_the_number(
    client: TestClient, company_a: TenantContext
) -> None:
    resp = _put(client, company_a.hr_headers, {"payout_account_number": "98765abc4321"})
    assert resp.status_code == 422
    assert "98765abc4321" not in resp.text, "R5: the 422 echoed the submitted number"


# ------------------------------------------------------------------- R6


def test_R6_reveal_true_returns_the_plain_number_to_hr_admin_and_owner_only(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    owner = _owner(db, company_a)
    for who, headers in (("hr_admin", company_a.hr_headers), ("owner", owner)):
        resp = _get(client, headers, "?reveal=true")
        assert resp.status_code == 200, f"R6: {who} reveal: {resp.text}"
        assert resp.json()["payout_account_number"] == ACCOUNT, f"R6: {who} must see the number"
    for headers in (company_a.employee_headers, company_a.manager_headers):
        assert _get(client, headers, "?reveal=true").status_code == 403, "R6: others get 403"


def test_R6_without_reveal_the_number_is_always_masked(
    client: TestClient, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    for query in ("", "?reveal=false", "?reveal=0"):
        resp = _get(client, company_a.hr_headers, query)
        assert resp.json()["payout_account_number"] == MASKED, f"R6: {query!r} must stay masked"


def test_R6_a_bad_reveal_value_gives_422(client: TestClient, company_a: TenantContext) -> None:
    assert _get(client, company_a.hr_headers, "?reveal=maybe").status_code == 422


def test_R6_every_reveal_writes_one_audit_row_without_the_number(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    for _ in range(3):
        assert _get(client, company_a.hr_headers, "?reveal=true").status_code == 200
    rows = _audit(db, company_a.company_id, "PAYOUT_ACCOUNT_REVEALED")
    assert len(rows) == 3, f"R6: three reveals must write three audit rows, got {len(rows)}"
    for row in rows:
        assert row.company_id == company_a.company_id, "R6: audit row needs the company"
        assert row.actor_user_id is not None, "R6: audit row needs who revealed"
        assert row.created_at is not None, "R6: audit row needs when"
        assert ACCOUNT not in str(row.details) and MASKED not in str(row.details), (
            "R6: audit row holds the number"
        )


def test_R6_reads_without_reveal_and_refused_reveals_write_no_reveal_row(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    _get(client, company_a.hr_headers)
    _get(client, company_a.employee_headers, "?reveal=true")
    assert _audit(db, company_a.company_id, "PAYOUT_ACCOUNT_REVEALED") == [], (
        "R6: only a successful reveal writes the audit row"
    )


def test_R6_revealing_when_no_number_is_stored_shows_nothing_and_writes_no_row(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    resp = _get(client, company_a.hr_headers, "?reveal=true")
    assert resp.status_code == 200 and resp.json()["payout_account_number"] is None, resp.text
    assert _audit(db, company_a.company_id, "PAYOUT_ACCOUNT_REVEALED") == [], (
        "R6: nothing was revealed, so no reveal audit row"
    )


def test_R6_a_revealed_response_must_not_be_cached(
    client: TestClient, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    resp = _get(client, company_a.hr_headers, "?reveal=true")
    assert "no-store" in resp.headers.get("cache-control", ""), "R6: reveal must be no-store"


def test_R6_reveal_is_limited_to_5_per_minute_per_user(
    client: TestClient, db: Session, company_a: TenantContext, limits_on
) -> None:
    _saved(client, company_a.hr_headers)
    codes = [_get(client, company_a.hr_headers, "?reveal=true").status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429, f"R6: reveal limit wrong: {codes}"
    assert len(_audit(db, company_a.company_id, "PAYOUT_ACCOUNT_REVEALED")) == 5, (
        "R6: the refused sixth reveal must not write an audit row"
    )
    other = _owner(db, company_a)
    assert _get(client, other, "?reveal=true").status_code == 200, (
        "R6: the reveal limit is per user, another user is not blocked"
    )


# ------------------------------------------------------------------- R7


@pytest.mark.parametrize("placeholder", [MASKED, "****9012", "************"])
def test_R7_sending_the_masked_value_back_never_overwrites_the_number(
    client: TestClient, db: Session, company_a: TenantContext, placeholder: str
) -> None:
    _saved(client, company_a.hr_headers)
    before = _blob(db, company_a.company_id)
    resp = _put(
        client,
        company_a.hr_headers,
        {"payout_account_number": placeholder, "pt_state": "Gujarat"},
    )
    assert resp.status_code == 200, f"R7: masked value back must be accepted: {resp.text}"
    assert resp.json()["pt_state"] == "Gujarat", "R7: the other field must still be saved"
    assert _blob(db, company_a.company_id) == before, "R7: the stored blob was overwritten"
    reveal = _get(client, company_a.hr_headers, "?reveal=true").json()
    assert reveal["payout_account_number"] == ACCOUNT, "R7: the stored number changed"


def test_R7_a_masked_value_with_other_digits_or_with_nothing_stored_gives_422(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    none_stored = _put(client, company_a.hr_headers, {"payout_account_number": MASKED})
    assert none_stored.status_code == 422, f"R7: masked with no number stored: {none_stored.text}"
    _saved(client, company_a.hr_headers)
    wrong = _put(client, company_a.hr_headers, {"payout_account_number": "********1111"})
    assert wrong.status_code == 422, f"R7: masked with other digits must give 422: {wrong.text}"
    assert _row(db, company_a.company_id)["payout_account_last4"] == LAST4


def test_R7_the_masked_value_alone_writes_no_audit_row(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    before = len(_audit(db, company_a.company_id, "STATUTORY_CONFIG_UPDATED"))
    _put(client, company_a.hr_headers, {"payout_account_number": MASKED})
    after = len(_audit(db, company_a.company_id, "STATUTORY_CONFIG_UPDATED"))
    assert after == before, "R7: sending the mask back alone must write no audit row"


def test_R7_an_unchanged_plain_number_writes_no_audit_row_and_keeps_the_blob(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    blob = _blob(db, company_a.company_id)
    before = len(_audit(db, company_a.company_id, "STATUTORY_CONFIG_UPDATED"))
    resp = _put(client, company_a.hr_headers, {"payout_account_number": ACCOUNT})
    assert resp.status_code == 200, resp.text
    assert len(_audit(db, company_a.company_id, "STATUTORY_CONFIG_UPDATED")) == before, (
        "R7: the same number sent again must write no audit row"
    )
    assert _blob(db, company_a.company_id) == blob, "R7: the same number must not be re-encrypted"


def test_R7_a_changed_number_writes_one_audit_row_with_field_names_only(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    before = len(_audit(db, company_a.company_id, "STATUTORY_CONFIG_UPDATED"))
    new = "999988887777"
    resp = _put(client, company_a.hr_headers, {"payout_account_number": new})
    assert resp.json()["payout_account_number"] == "********7777", resp.text
    rows = _audit(db, company_a.company_id, "STATUTORY_CONFIG_UPDATED")
    assert len(rows) == before + 1, "R7: one change must write exactly one audit row"
    newest = max(rows, key=lambda r: r.created_at)
    assert newest.details == {"fields": ["payout_account_number"]}, (
        f"R7: audit must hold the field name only: {newest.details}"
    )
    row = _row(db, company_a.company_id)
    assert row["payout_account_last4"] == "7777", "R7: last4 must follow the new number"
    plain = decrypt_field(
        bytes(row["payout_account_number_enc"]), company_id=company_a.company_id, column=COLUMN
    )
    assert plain == new, "R7: the new number must be stored"


def test_R7_clearing_the_number_removes_blob_and_last4(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    resp = _put(client, company_a.hr_headers, {"payout_account_number": None})
    assert resp.status_code == 200 and resp.json()["payout_account_number"] is None, resp.text
    row = _row(db, company_a.company_id)
    assert row["payout_account_number_enc"] is None and row["payout_account_last4"] is None, (
        "R7: clearing must remove both the blob and last4"
    )


def test_R7_the_update_and_its_audit_row_are_one_save(
    db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    hr = (
        db.query(User)
        .filter(User.company_id == company_a.company_id, User.role == UserRole.hr_admin)
        .one()
    )
    service = StatutoryConfigService(db)
    service.update(company_a.company_id, StatutoryConfigUpdateRequest(**FULL), hr)
    before = _blob(db, company_a.company_id)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditService, "record", _boom)
    with pytest.raises(RuntimeError):
        service.update(
            company_a.company_id,
            StatutoryConfigUpdateRequest(payout_account_number="999988887777"),
            hr,
        )
    db.rollback()
    assert _blob(db, company_a.company_id) == before, (
        "R7: the number was saved although its audit row failed"
    )


def test_R7_a_failed_encryption_leaves_the_old_value(
    client: TestClient, db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saved(client, company_a.hr_headers)
    before = _blob(db, company_a.company_id)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", None)
    resp = _put(
        client,
        company_a.hr_headers,
        {"payout_account_number": "999988887777", "payout_bank_name": "Other Bank"},
    )
    assert resp.status_code == 503, f"R7: no key must give 503: {resp.text}"
    assert _blob(db, company_a.company_id) == before, "R7: the old number must stay"
    assert _row(db, company_a.company_id)["payout_bank_name"] == BANK, (
        "R7: the whole save is refused, the bank name must stay too"
    )


# ------------------------------------------------------------------- R8


def test_R8_saving_without_a_key_is_refused_with_503_in_every_environment(
    client: TestClient, db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    for environment in ("development", "staging", "production"):
        monkeypatch.setattr(settings, "ENVIRONMENT", environment)
        monkeypatch.setattr(settings, "ENCRYPTION_KEY", None)
        resp = _put(client, company_a.hr_headers, {"payout_account_number": ACCOUNT})
        assert resp.status_code == 503, f"R8: {environment}: no key must give 503: {resp.text}"
        assert resp.json()["error"]["code"] == "encryption_unavailable", resp.text
    row = _row(db, company_a.company_id)
    assert row is None or row["payout_account_number_enc"] is None, "R8: nothing may be saved"


def test_R8_an_empty_key_counts_as_no_key(
    client: TestClient, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    resp = _put(client, company_a.hr_headers, {"payout_account_number": ACCOUNT})
    assert resp.status_code == 503, f"R8: an empty key must give 503: {resp.text}"


def test_R8_revealing_without_a_key_is_refused_and_writes_no_audit_row(
    client: TestClient, db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saved(client, company_a.hr_headers)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", None)
    resp = _get(client, company_a.hr_headers, "?reveal=true")
    assert resp.status_code == 503, f"R8: reveal without a key must give 503: {resp.text}"
    assert _audit(db, company_a.company_id, "PAYOUT_ACCOUNT_REVEALED") == []
    assert _get(client, company_a.hr_headers).status_code == 200, (
        "R8: the masked view needs no key and must keep working"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-real-key-value",
        base64.b64encode(b"too short").decode(),
        base64.b64encode(bytes(33)).decode(),
    ],
)
def test_R8_a_key_that_is_not_32_bytes_fails_clearly_and_is_never_printed(
    client: TestClient,
    company_a: TenantContext,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    bad: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", bad)
    resp = _put(client, company_a.hr_headers, {"payout_account_number": ACCOUNT})
    assert resp.status_code == 503, f"R8: a bad key must give 503: {resp.text}"
    assert bad not in resp.text, "R8: the key was printed in the response"
    assert bad not in caplog.text, "R8: the key was printed in a log line"
    assert "32" in resp.text, "R8: the error must say what a good key is"


def test_R8_the_key_version_setting_is_written_into_the_blob(
    client: TestClient, db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 3)
    _saved(client, company_a.hr_headers)
    assert _blob(db, company_a.company_id)[0] == 3, "R8: the version byte must be the setting"


def test_R8_after_a_rotation_an_old_blob_is_read_through_the_previous_keys_setting(
    client: TestClient, db: Session, company_a: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saved(client, company_a.hr_headers)
    assert _blob(db, company_a.company_id)[0] == 1
    new_key = base64.b64encode(bytes([7]) * 32).decode()
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", new_key)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_VERSION", 2)

    monkeypatch.setattr(settings, "ENCRYPTION_PREVIOUS_KEYS", {})
    lost = _get(client, company_a.hr_headers, "?reveal=true")
    assert lost.status_code == 500 and "version 1" in lost.text, (
        f"R8: an unavailable old version must fail clearly: {lost.text}"
    )

    monkeypatch.setattr(settings, "ENCRYPTION_PREVIOUS_KEYS", {1: TEST_ENCRYPTION_KEY})
    found = _get(client, company_a.hr_headers, "?reveal=true")
    assert found.status_code == 200 and found.json()["payout_account_number"] == ACCOUNT, (
        f"R8: the previous key must read the old blob: {found.text}"
    )
    _put(client, company_a.hr_headers, {"payout_account_number": "999988887777"})
    assert _blob(db, company_a.company_id)[0] == 2, "R8: new saves must use the new version"


def test_R8_a_blob_with_an_unknown_version_fails_clearly(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    blob = bytearray(_blob(db, company_a.company_id))
    blob[0] = 9
    db.execute(
        text("UPDATE statutory_configs SET payout_account_number_enc = :b WHERE company_id = :c"),
        {"b": bytes(blob), "c": company_a.company_id},
    )
    db.commit()
    resp = _get(client, company_a.hr_headers, "?reveal=true")
    assert resp.status_code == 500 and "version 9" in resp.text, f"R8: unknown version: {resp.text}"


def test_R8_the_key_never_reaches_the_audit_log(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    _saved(client, company_a.hr_headers)
    _get(client, company_a.hr_headers, "?reveal=true")
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    for row in db.query(AuditLog).filter(AuditLog.company_id == company_a.company_id):
        assert TEST_ENCRYPTION_KEY not in f"{row.details}", "R8: the key is in an audit row"


def test_R8_no_key_is_written_in_the_app_source_and_the_env_example_says_how_to_make_one() -> None:
    for path in (REPO_ROOT / "app").rglob("*.py"):
        assert TEST_ENCRYPTION_KEY not in path.read_text(), f"R8: a key literal is in {path}"
    example = (REPO_ROOT / ".env.example").read_text()
    assert "ENCRYPTION_KEY" in example and "base64" in example, "R8: .env.example needs a hint"
    assert "ENCRYPTION_PREVIOUS_KEYS" in example, "R8: .env.example must mention rotation"


# ------------------------------------------------------------------- R9


def test_R9_writes_are_limited_to_30_per_minute_per_user_not_per_ip(
    client: TestClient, db: Session, company_a: TenantContext, limits_on
) -> None:
    body = {"pt_state": "Gujarat"}
    codes = [_put(client, company_a.hr_headers, body).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429, f"R9: PUT limit wrong: {codes[-3:]}"
    other, _ = _extra_user(db, company_a.company_id, UserRole.hr_admin)
    assert _put(client, other, {"pt_state": "Gujarat"}).status_code == 200, (
        "R9: another user from the same IP must not be blocked: the limit is per user"
    )


def test_R9_reads_are_limited_to_60_per_minute_per_user(
    client: TestClient, db: Session, company_a: TenantContext, limits_on
) -> None:
    codes = [_get(client, company_a.hr_headers).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R9: GET limit wrong: {codes[-3:]}"
    other, _ = _extra_user(db, company_a.company_id, UserRole.hr_admin)
    assert _get(client, other).status_code == 200, "R9: the read limit is per user"


# ------------------------------------------------------------------- R10


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
    assert Path(__file__).name == "test_5_7_payout_accounts.py"
