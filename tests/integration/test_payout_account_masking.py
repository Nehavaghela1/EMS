from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.payroll.models import StatutoryConfig
from app.modules.platform.models import AuditLog
from tests.conftest import TenantContext


def test_statutory_config_payout_account_number_masking(
    client: TestClient, db: Session, company_a: TenantContext
):
    """
    Task: mask payout_account_number in StatutoryConfigResponse (app/modules/payroll/schemas.py).
    - Responses return only the last 4 characters, for example "******1234".
      A value of 4 characters or fewer is fully masked. None stays None.
    - PUT still accepts the full number and stores it as before.
    - If a PUT sends back the masked form unchanged, do not overwrite the stored value.
    - Audit details still contain no value (only field names in 'fields').
    """
    # 1. Initially payout_account_number is None
    res = client.get("/api/v1/payroll/statutory-config", headers=company_a.hr_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["payout_account_number"] is None

    # 2. PUT with a full number returns masked
    account_num = "987654321012"
    put_res = client.put(
        "/api/v1/payroll/statutory-config",
        headers=company_a.hr_headers,
        json={"payout_account_number": account_num},
    )
    assert put_res.status_code == 200
    put_data = put_res.json()
    expected_masked = "********1012"
    assert put_data["payout_account_number"] == expected_masked, (
        f"Expected {expected_masked}, got {put_data['payout_account_number']}"
    )

    # 3. GET masked
    get_res = client.get("/api/v1/payroll/statutory-config", headers=company_a.hr_headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["payout_account_number"] == expected_masked

    # 4. Short value masking (<= 4 chars)
    short_put_res = client.put(
        "/api/v1/payroll/statutory-config",
        headers=company_a.hr_headers,
        json={"payout_account_number": "1234"},
    )
    assert short_put_res.status_code == 200
    assert short_put_res.json()["payout_account_number"] == "****"

    # Reset back to full account_num
    client.put(
        "/api/v1/payroll/statutory-config",
        headers=company_a.hr_headers,
        json={"payout_account_number": account_num},
    )

    # 5. PUT with the masked form leaves the stored value unchanged
    # Simulates frontend submitting back the response it received (e.g. updating pt_state)
    masked_put_res = client.put(
        "/api/v1/payroll/statutory-config",
        headers=company_a.hr_headers,
        json={
            "payout_account_number": expected_masked,
            "pt_state": "Maharashtra",
        },
    )
    assert masked_put_res.status_code == 200
    masked_put_data = masked_put_res.json()
    assert masked_put_data["payout_account_number"] == expected_masked
    assert masked_put_data["pt_state"] == "Maharashtra"

    # Verify directly from DB that the stored value is still the original unmasked account_num
    db.expire_all()
    cfg = db.scalar(
        select(StatutoryConfig).where(StatutoryConfig.company_id == company_a.company_id)
    )
    assert cfg is not None
    assert cfg.payout_account_number == account_num, (
        f"Stored value was modified! Expected {account_num}, got {cfg.payout_account_number}"
    )

    # 6. None case: explicitly setting payout_account_number to None or clearing it
    # Note: if a user explicitly passes None, it clears it to None
    none_put_res = client.put(
        "/api/v1/payroll/statutory-config",
        headers=company_a.hr_headers,
        json={"payout_account_number": None},
    )
    assert none_put_res.status_code == 200
    assert none_put_res.json()["payout_account_number"] is None

    db.expire_all()
    cfg_none = db.scalar(
        select(StatutoryConfig).where(StatutoryConfig.company_id == company_a.company_id)
    )
    assert cfg_none is not None
    assert cfg_none.payout_account_number is None

    # 7. Audit details check: audit details still contain no value
    audit_logs = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "STATUTORY_CONFIG_UPDATED",
        )
        .order_by(AuditLog.created_at.desc())
    ).all()
    assert len(audit_logs) > 0
    for log in audit_logs:
        # Details should only contain the list of fields updated, never values or secrets
        assert log.details is not None
        assert "fields" in log.details
        # Ensure no account number or secret leaked into details
        assert account_num not in str(log.details)
        assert expected_masked not in str(log.details)
