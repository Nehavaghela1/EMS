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
