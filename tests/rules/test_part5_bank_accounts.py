"""Part 5 tests: bank accounts, masked end to end.

Rules:
- The response is masked for employee, hr_admin and owner.
- Submitting a masked value with bullet returns 422 and leaves the stored value unchanged.
- A change creates a new active row and deactivates the old.
- The full number appears in no log or error.
"""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_field
from app.modules.identity.models import UserRole
from app.modules.payroll.models import EmployeeBankAccount
from app.modules.payroll.schemas import BankAccountRequest
from tests.conftest import TenantContext, _make_user_headers
from tests.rules.test_5_4_payroll_runs import _create_employee, _link_user_to_employee

ME = "/api/v1/payroll/bank-account/me"
EMPLOYEES = "/api/v1/payroll/employees"
ACCOUNT = "987654321012"
LAST4 = "1012"
BULLET_MASK = "••••1012"
VALID_BANK = {
    "account_holder": "Asha Rao",
    "bank_name": "State Bank of India",
    "account_number": ACCOUNT,
    "ifsc_code": "SBIN0001234",
}


def _for(emp_id: str) -> str:
    return f"{EMPLOYEES}/{emp_id}/bank-account"


def test_part5_bullet_in_account_number_rejected_with_422():
    with pytest.raises(ValueError, match="bullet"):
        BankAccountRequest(
            account_holder="Asha Rao",
            bank_name="SBI",
            account_number="••••1234",
            ifsc_code="SBIN0001234",
        )


def test_part5_responses_are_masked_and_never_leak_plain_number(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)
    company_id = company_a.company_id
    hr_headers = company_a.hr_headers
    owner_headers = _make_user_headers(db, company_id, UserRole.owner)

    # Create employee with linked user and employee headers
    emp_dict = _create_employee(client, hr_headers)
    emp_id = emp_dict["id"]
    emp_headers, _ = _link_user_to_employee(db, company_id, emp_id, UserRole.employee)

    # Employee saves details
    put_res = client.put(ME, json=VALID_BANK, headers=emp_headers)
    assert put_res.status_code == 200, put_res.text
    put_data = put_res.json()
    assert put_data["account_number"].endswith(LAST4)
    assert ACCOUNT not in put_res.text

    # Employee views details
    get_emp = client.get(ME, headers=emp_headers)
    assert get_emp.status_code == 200
    assert get_emp.json()["account_number"].endswith(LAST4)
    assert ACCOUNT not in get_emp.text

    # HR Admin views details
    get_hr = client.get(_for(emp_id), headers=hr_headers)
    assert get_hr.status_code == 200
    assert get_hr.json()["account_number"].endswith(LAST4)
    assert ACCOUNT not in get_hr.text

    # Owner views details
    get_owner = client.get(_for(emp_id), headers=owner_headers)
    assert get_owner.status_code == 200
    assert get_owner.json()["account_number"].endswith(LAST4)
    assert ACCOUNT not in get_owner.text

    # Stored correctly encrypted in DB
    rows = (
        db.execute(
            select(EmployeeBankAccount).where(
                EmployeeBankAccount.company_id == company_id,
                EmployeeBankAccount.employee_id == uuid.UUID(emp_id),
                EmployeeBankAccount.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    stored_row = rows[0]
    decrypted = decrypt_field(
        bytes(stored_row.account_number_enc),
        company_id=company_id,
        column="bank_account_number",
    )
    assert decrypted == ACCOUNT

    # Submitting bullet returns 422 and leaves stored value unchanged
    bad_payload = dict(VALID_BANK)
    bad_payload["account_number"] = BULLET_MASK
    bad_put = client.put(ME, json=bad_payload, headers=emp_headers)
    assert bad_put.status_code == 422
    assert "bullet" in bad_put.text.lower()
    assert ACCOUNT not in bad_put.text

    # Verify stored row still active and unchanged
    db.expire_all()
    rows_after = (
        db.execute(
            select(EmployeeBankAccount).where(
                EmployeeBankAccount.company_id == company_id,
                EmployeeBankAccount.employee_id == uuid.UUID(emp_id),
                EmployeeBankAccount.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    assert len(rows_after) == 1
    assert rows_after[0].id == stored_row.id

    # A valid change creates a new active row and deactivates the old
    new_payload = dict(VALID_BANK)
    new_payload["account_number"] = "112233445566"
    new_put = client.put(ME, json=new_payload, headers=emp_headers)
    assert new_put.status_code == 200
    assert new_put.json()["account_number"].endswith("5566")

    db.expire_all()
    all_rows = (
        db.execute(
            select(EmployeeBankAccount).where(
                EmployeeBankAccount.company_id == company_id,
                EmployeeBankAccount.employee_id == uuid.UUID(emp_id),
            )
        )
        .scalars()
        .all()
    )
    assert len(all_rows) == 2
    active_rows = [r for r in all_rows if r.is_active]
    inactive_rows = [r for r in all_rows if not r.is_active]
    assert len(active_rows) == 1
    assert len(inactive_rows) == 1
    assert active_rows[0].account_last4 == "5566"
    assert inactive_rows[0].account_last4 == LAST4

    # Full number appears in no log or error
    assert ACCOUNT not in caplog.text


def test_part5_bank_account_reveal_rules(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
    company_b: TenantContext,
    super_admin_headers: dict[str, str],
):
    from app.db.rls import bind_tenant_to_session
    from app.modules.platform.models import AuditLog

    company_id = company_a.company_id
    hr_headers = company_a.hr_headers
    owner_headers = _make_user_headers(db, company_id, UserRole.owner)

    # Create employee 1
    emp1_dict = _create_employee(client, hr_headers)
    emp1_id = emp1_dict["id"]
    emp1_headers, _ = _link_user_to_employee(db, company_id, emp1_id, UserRole.employee)

    # Create employee 2
    emp2_dict = _create_employee(client, hr_headers)
    emp2_id = emp2_dict["id"]
    emp2_headers, _ = _link_user_to_employee(db, company_id, emp2_id, UserRole.employee)

    # Save bank details for employee 1
    put_res = client.put(ME, json=VALID_BANK, headers=emp1_headers)
    assert put_res.status_code == 200

    # 1. Normal GET of the same employee still returns the masked value
    get_res = client.get(ME, headers=emp1_headers)
    assert get_res.status_code == 200
    assert get_res.json()["account_number"] == "********1012"
    assert get_res.json()["account_number"] != ACCOUNT

    get_emp_res = client.get(_for(emp1_id), headers=hr_headers)
    assert get_emp_res.status_code == 200
    assert get_emp_res.json()["account_number"] == "********1012"
    assert get_emp_res.json()["account_number"] != ACCOUNT

    # 2. An employee reveals their OWN number and gets the full value
    reveal_self = client.post("/api/v1/payroll/bank-account/me/reveal", headers=emp1_headers)
    assert reveal_self.status_code == 200
    assert reveal_self.json()["account_number"] == ACCOUNT
    assert reveal_self.headers.get("cache-control") == "no-store"

    # 3. An hr_admin reveals one of their employees' numbers and gets the full value
    reveal_hr = client.post(
        f"/api/v1/payroll/employees/{emp1_id}/bank-account/reveal", headers=hr_headers
    )
    assert reveal_hr.status_code == 200
    assert reveal_hr.json()["account_number"] == ACCOUNT
    assert reveal_hr.headers.get("cache-control") == "no-store"

    # 4. An owner can do the same
    reveal_owner = client.post(
        f"/api/v1/payroll/employees/{emp1_id}/bank-account/reveal", headers=owner_headers
    )
    assert reveal_owner.status_code == 200
    assert reveal_owner.json()["account_number"] == ACCOUNT
    assert reveal_owner.headers.get("cache-control") == "no-store"

    # 5. A plain employee revealing a DIFFERENT employee's number gets 404
    reveal_other = client.post(
        f"/api/v1/payroll/employees/{emp2_id}/bank-account/reveal", headers=emp1_headers
    )
    assert reveal_other.status_code == 404

    # 6. super_admin is refused (403 forbidden - no company context)
    reveal_sa_me = client.post(
        "/api/v1/payroll/bank-account/me/reveal", headers=super_admin_headers
    )
    assert reveal_sa_me.status_code == 403

    reveal_sa_emp = client.post(
        f"/api/v1/payroll/employees/{emp1_id}/bank-account/reveal", headers=super_admin_headers
    )
    assert reveal_sa_emp.status_code == 403

    # 7. Cross-company access returns 404 (nobody may reveal another company's account)
    hr_b_headers = company_b.hr_headers
    reveal_cross = client.post(
        f"/api/v1/payroll/employees/{emp1_id}/bank-account/reveal", headers=hr_b_headers
    )
    assert reveal_cross.status_code == 404

    # 8. An audit row is written and contains ONLY the last four (never full number)
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_id,
            AuditLog.action == "BANK_ACCOUNT_REVEALED",
        )
        .all()
    )
    assert len(audit_rows) >= 3  # self, hr, owner
    for row in audit_rows:
        details = str(row.details)
        assert ACCOUNT not in details
        assert LAST4 in details
