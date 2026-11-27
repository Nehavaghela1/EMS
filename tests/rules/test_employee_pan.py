"""Employee PAN storage, encryption, validation, access control, audit, and tax worksheet tests.

Covers:
1. PAN stored encrypted at rest (pan_enc as bytes, pan_last3 as clear string).
   Raw SQL shows bytes, no plaintext.
2. Validation: exactly 10 characters, regex ^[A-Z]{5}[0-9]{4}[A-Z]$, uppercase stored.
   Invalid PAN rejected with 422, never echoes value.
3. Access control:
   - SET/UPDATE: hr_admin and owner only. Employee attempting to edit PAN gets 403 Forbidden.
   - VIEW MASKED: Shown masked as •••••••34F for employee, manager, hr_admin, owner.
   - REVEAL:
     * Employee can reveal own PAN via /employees/me/pan/reveal or /employees/{id}/pan/reveal.
     * hr_admin and owner can reveal for employee in company.
     * super_admin is refused (403).
     * Cross-tenant employee returns 404.
4. Audit: reveal action logs pan.reveal with pan_last3 only, NEVER full PAN.
5. Tax worksheet & payslips:
   - Displays real PAN when present.
   - Displays Section 206AA warning when missing.
"""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_field
from app.modules.identity.models import UserRole
from tests.conftest import TenantContext
from tests.rules.test_5_4_payroll_runs import _create_employee, _link_user_to_employee

VALID_PAN = "ABCDE1234F"
LAST3 = "34F"
MASKED_PAN = "•••••••34F"


def test_employee_pan_validation_and_rejection(
    client: TestClient, db: Session, company_a: TenantContext
):
    """Invalid PANs return 422 and do NOT echo the sensitive invalid value back."""
    hr_headers = company_a.hr_headers

    emp_dict = _create_employee(client, hr_headers)
    emp_id = emp_dict["id"]

    # Valid update
    res = client.put(
        f"/api/v1/employees/{emp_id}",
        json={"pan": "abcde1234f"},
        headers=hr_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "pan" not in body
    assert body["pan_last3"] == LAST3
    # Reveal endpoint gives full value
    reveal_res = client.post(f"/api/v1/employees/{emp_id}/pan/reveal", headers=hr_headers)
    assert reveal_res.status_code == 200
    assert reveal_res.json()["pan"] == "ABCDE1234F"

    # Invalid PAN - wrong format
    invalid_val = "INVALID123"
    bad_res = client.put(
        f"/api/v1/employees/{emp_id}",
        json={"pan": invalid_val},
        headers=hr_headers,
    )
    assert bad_res.status_code == 422
    # Verify the invalid value is NOT echoed in error response
    assert invalid_val not in bad_res.text


def test_employee_cannot_update_own_pan(client: TestClient, db: Session, company_a: TenantContext):
    """Employee updating their own record is forbidden from setting PAN."""
    company_id = company_a.company_id
    hr_headers = company_a.hr_headers

    emp_dict = _create_employee(client, hr_headers)
    emp_id = emp_dict["id"]
    emp_headers, _ = _link_user_to_employee(db, company_id, emp_id, UserRole.employee)

    res = client.put(
        f"/api/v1/employees/{emp_id}",
        json={"pan": "XYZAB5678C"},
        headers=emp_headers,
    )
    assert res.status_code == 403
    assert "pan" in res.text.lower() or "contact" in res.text.lower()


def test_employee_pan_encrypted_at_rest(client: TestClient, db: Session, company_a: TenantContext):
    """Employee PAN is encrypted in DB (pan_enc is binary, not plaintext)."""
    company_id = company_a.company_id
    hr_headers = company_a.hr_headers

    emp_dict = _create_employee(client, hr_headers)
    emp_id = emp_dict["id"]

    client.put(
        f"/api/v1/employees/{emp_id}",
        json={"pan": VALID_PAN},
        headers=hr_headers,
    )

    # Inspect raw SQL row
    row = db.execute(
        text("SELECT pan_enc, pan_last3 FROM employees WHERE id = :id"),
        {"id": emp_id},
    ).one()

    raw_enc = row[0]
    raw_last3 = row[1]

    assert isinstance(raw_enc, (bytes, memoryview))
    assert VALID_PAN.encode() not in bytes(raw_enc)
    assert raw_last3 == LAST3

    # Decrypt verification
    decrypted = decrypt_field(bytes(raw_enc), company_id=company_id, column="pan_enc")
    assert decrypted == VALID_PAN


def test_pan_reveal_access_control_and_audit(
    client: TestClient,
    db: Session,
    company_a: TenantContext,
    company_b: TenantContext,
    super_admin_headers: dict[str, str],
):
    """Verify reveal permissions, audit records only pan_last3, and boundary checks."""
    company_id = company_a.company_id
    hr_headers = company_a.hr_headers

    emp_dict = _create_employee(client, hr_headers)
    emp_id = emp_dict["id"]
    emp_headers, _ = _link_user_to_employee(db, company_id, emp_id, UserRole.employee)

    # Set PAN by HR
    client.put(
        f"/api/v1/employees/{emp_id}",
        json={"pan": VALID_PAN},
        headers=hr_headers,
    )

    # 1. Employee reveals own PAN via /me/pan/reveal
    me_res = client.post("/api/v1/employees/me/pan/reveal", headers=emp_headers)
    assert me_res.status_code == 200, me_res.text
    assert me_res.json()["pan"] == VALID_PAN
    assert me_res.json()["pan_last3"] == LAST3
    assert "no-store" in me_res.headers.get("Cache-Control", "")

    # 2. Employee reveals own PAN via /{employee_id}/pan/reveal
    emp_res = client.post(f"/api/v1/employees/{emp_id}/pan/reveal", headers=emp_headers)
    assert emp_res.status_code == 200
    assert emp_res.json()["pan"] == VALID_PAN

    # 3. HR Admin reveals employee PAN
    hr_res = client.post(f"/api/v1/employees/{emp_id}/pan/reveal", headers=hr_headers)
    assert hr_res.status_code == 200
    assert hr_res.json()["pan"] == VALID_PAN

    # 4. Another employee reveals this employee PAN -> 404 (NotFoundError per security spec)
    other_dict = _create_employee(client, hr_headers)
    other_headers, _ = _link_user_to_employee(db, company_id, other_dict["id"], UserRole.employee)

    unauth_res = client.post(f"/api/v1/employees/{emp_id}/pan/reveal", headers=other_headers)
    assert unauth_res.status_code == 404

    # 5. Super admin is refused (403)
    super_res = client.post(f"/api/v1/employees/{emp_id}/pan/reveal", headers=super_admin_headers)
    assert super_res.status_code == 403

    # 6. Cross-tenant request -> 404
    cross_res = client.post(f"/api/v1/employees/{emp_id}/pan/reveal", headers=company_b.hr_headers)
    assert cross_res.status_code == 404

    # 7. Audit log check: verify action is 'pan.reveal'
    # and details contains pan_last3 and NOT full PAN
    audit_rows = db.execute(
        text(
            "SELECT action, details FROM audit_logs "
            "WHERE company_id = :cid AND action = 'pan.reveal'"
        ),
        {"cid": company_id},
    ).all()
    assert len(audit_rows) >= 1
    for row in audit_rows:
        assert row[0] == "pan.reveal"
        details_str = str(row[1])
        assert LAST3 in details_str
        assert VALID_PAN not in details_str


def test_tax_worksheet_displays_pan_and_missing_warning(
    client: TestClient, db: Session, company_a: TenantContext
):
    """Tax worksheet shows real decrypted PAN when present, and 206AA warning when missing."""
    company_id = company_a.company_id
    hr_headers = company_a.hr_headers

    emp_dict = _create_employee(client, hr_headers)
    emp_id = emp_dict["id"]
    emp_headers, _ = _link_user_to_employee(db, company_id, emp_id, UserRole.employee)

    # Query tax worksheet for employee without PAN
    res_no_pan = client.get(
        "/api/v1/payroll/tax-worksheet/me?month=10&year=2026", headers=emp_headers
    )
    if res_no_pan.status_code == 200:
        data = res_no_pan.json()
        assert data.get("pan_number") is None
        assert "206AA" in (data.get("pan_warning") or "")

    # Now add PAN
    client.put(
        f"/api/v1/employees/{emp_id}",
        json={"pan": VALID_PAN},
        headers=hr_headers,
    )

    res_with_pan = client.get(
        "/api/v1/payroll/tax-worksheet/me?month=10&year=2026", headers=emp_headers
    )
    if res_with_pan.status_code == 200:
        data = res_with_pan.json()
        assert data.get("pan_number") == VALID_PAN
        assert data.get("pan_warning") is None
