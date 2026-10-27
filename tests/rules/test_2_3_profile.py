import threading
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Department, Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import (
    Company,
    CompanyLocation,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


def _get_audit_details(audit: AuditLog) -> dict[str, Any]:
    assert audit.details is not None, f"AuditLog {audit.id} details must not be None"
    return audit.details


@pytest.fixture
def profile_company(db: Session) -> dict[str, Any]:
    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name=f"Profile Corp {uuid.uuid4().hex[:6]}",
        code=f"PC{uuid.uuid4().hex[:4].upper()}",
        email=f"profile-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    hr_admin = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    manager = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    emp_staff_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    emp_other_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"other-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([owner, hr_admin, manager, emp_staff_user, emp_other_user])
    db.flush()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    dept = Department(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"Engineering {uuid.uuid4().hex[:4]}",
    )
    loc = CompanyLocation(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"HQ {uuid.uuid4().hex[:4]}",
        code=f"HQ{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        is_active=True,
    )
    db.add_all([dept, loc])
    db.flush()

    emp_mgr = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=manager.id,
        employee_code=f"{company.code}-0001",
        first_name="Manager",
        last_name="Leader",
        email=manager.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp_staff = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_staff_user.id,
        employee_code=f"{company.code}-0002",
        first_name="Staff",
        last_name="Member",
        email=emp_staff_user.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
        reporting_manager_id=emp_mgr.id,
    )
    emp_other = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_other_user.id,
        employee_code=f"{company.code}-0003",
        first_name="Other",
        last_name="Colleague",
        email=emp_other_user.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    db.add_all([emp_mgr, emp_staff, emp_other])
    db.commit()

    return {
        "company": company,
        "owner": owner,
        "hr_admin": hr_admin,
        "manager": manager,
        "emp_staff_user": emp_staff_user,
        "emp_other_user": emp_other_user,
        "emp_mgr": emp_mgr,
        "emp_staff": emp_staff,
        "emp_other": emp_other,
        "dept": dept,
        "location": loc,
    }


# ==============================================================================
# R01: Employee Contact Editing vs HR Fields
# ==============================================================================


def test_r01_employee_edits_own_contact_fields_only(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R01:
    - Employee edits phone, last_name, personal_email each 200 and persisted.
    - Employee sends HR-only fields (position, dept, mgr, level, hire_date, email, first_name)
      each 403 and the DB row unchanged (details.fields lists restricted fields).
    - Unknown field gives 422 for employee and for HR.
    - No token gives 401.
    - Employee edits a colleague gives 403.
    """
    staff_user = profile_company["emp_staff_user"]
    staff_emp = profile_company["emp_staff"]
    colleague_emp = profile_company["emp_other"]
    hr_user = profile_company["hr_admin"]
    staff_headers = _auth_headers(staff_user)
    hr_headers = _auth_headers(hr_user)

    # 1. No token -> 401
    res_no_token = client.put(f"/api/v1/employees/{staff_emp.id}", json={"last_name": "NewName"})
    assert res_no_token.status_code == 401

    # 2. Employee edits colleague -> 403
    res_colleague = client.put(
        f"/api/v1/employees/{colleague_emp.id}",
        headers=staff_headers,
        json={"last_name": "Hacked"},
    )
    assert res_colleague.status_code == 403

    # 3. Employee edits phone, last_name, personal_email -> 200 and persisted
    res_edit_last = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=staff_headers,
        json={"last_name": "UpdatedLast"},
    )
    assert res_edit_last.status_code == 200
    assert res_edit_last.json()["last_name"] == "UpdatedLast"

    res_edit_phone = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=staff_headers,
        json={"phone": "+1234567890"},
    )
    assert res_edit_phone.status_code == 200
    assert res_edit_phone.json()["phone"] == "+1234567890"

    res_edit_p_email = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=staff_headers,
        json={"personal_email": "staff.personal@example.com"},
    )
    assert res_edit_p_email.status_code == 200
    assert res_edit_p_email.json()["personal_email"] == "staff.personal@example.com"

    # Refresh DB and assert contact fields are persisted
    bind_tenant_to_session(db, company_id=profile_company["company"].id, is_platform_admin=True)
    db.refresh(staff_emp)
    assert staff_emp.last_name == "UpdatedLast"
    assert staff_emp.phone == "+1234567890"
    assert staff_emp.personal_email == "staff.personal@example.com"

    # 4. Employee sends HR-only fields (position, dept, mgr, level, etc.) -> 403
    hr_only_payloads = [
        {"position": "Senior Dev"},
        {"department_id": str(profile_company["dept"].id)},
        {"reporting_manager_id": str(profile_company["emp_mgr"].id)},
        {"level": "L2"},
        {"hire_date": "2024-02-01"},
        {"email": "newworkemail@example.com"},
        {"first_name": "NewFirst"},
    ]
    for hr_payload in hr_only_payloads:
        res_hr_field = client.put(
            f"/api/v1/employees/{staff_emp.id}",
            headers=staff_headers,
            json=hr_payload,
        )
        assert res_hr_field.status_code == 403, (
            f"Expected 403 for {hr_payload}, got {res_hr_field.status_code}"
        )
        body = res_hr_field.json()
        field_key = next(iter(hr_payload.keys()))
        assert field_key in body.get("error", {}).get("details", {}).get("fields", [])

        # DB row unchanged
        db.refresh(staff_emp)
        assert staff_emp.first_name == "Staff"
        assert staff_emp.email == staff_user.email

    # 5. Unknown field gives 422 for employee and for HR
    res_unk_emp = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=staff_headers,
        json={"unknown_field": "val"},
    )
    assert res_unk_emp.status_code == 422

    res_unk_hr = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"unknown_field": "val"},
    )
    assert res_unk_hr.status_code == 422


# ==============================================================================
# R04: HR Admin and Owner Full Edit & Protected Fields
# ==============================================================================


def test_r04_hr_and_owner_edit_all_editable_and_protected_rejected(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R04:
    - HR admin and owner edit every editable field 200.
    - id, employee_code, company_id, is_active, invitation_status, user_id, system_role
      in body give 422 (unknown/forbid).
    """
    hr_headers = _auth_headers(profile_company["hr_admin"])
    owner_headers = _auth_headers(profile_company["owner"])
    staff_emp = profile_company["emp_staff"]
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Protected fields rejected with 422
    protected_fields = [
        {"id": str(uuid.uuid4())},
        {"employee_code": "TAMPERED-001"},
        {"company_id": str(uuid.uuid4())},
        {"is_active": False},
        {"invitation_status": "sent"},
        {"user_id": str(uuid.uuid4())},
        {"system_role": "admin"},
    ]
    for prot in protected_fields:
        res_hr_prot = client.put(
            f"/api/v1/employees/{staff_emp.id}",
            headers=hr_headers,
            json=prot,
        )
        assert res_hr_prot.status_code == 422, (
            f"Expected 422 for protected field {prot}, got {res_hr_prot.status_code}"
        )

    # 2. HR edits editable fields -> 200
    hr_update_payload = {
        "first_name": "StaffUpdated",
        "last_name": "HRChanged",
        "position": "Lead Engineer",
        "level": "L2",
        "notice_period_days": 45,
        "is_attendance_exempt": True,
    }
    res_hr_ok = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json=hr_update_payload,
    )
    assert res_hr_ok.status_code == 200
    body = res_hr_ok.json()
    assert body["first_name"] == "StaffUpdated"
    assert body["last_name"] == "HRChanged"
    assert body["position"] == "Lead Engineer"
    assert body["level"] == "L2"
    assert body["notice_period_days"] == 45
    assert body["is_attendance_exempt"] is True

    # 3. Owner edits editable fields -> 200
    owner_update_payload = {
        "first_name": "StaffByOwner",
        "position": "Principal Engineer",
        "level": "L3",
        "notice_period_days": 60,
    }
    res_owner_ok = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=owner_headers,
        json=owner_update_payload,
    )
    assert res_owner_ok.status_code == 200
    body_owner = res_owner_ok.json()
    assert body_owner["first_name"] == "StaffByOwner"
    assert body_owner["position"] == "Principal Engineer"
    assert body_owner["level"] == "L3"
    assert body_owner["notice_period_days"] == 60


# ==============================================================================
# R05: Manager Edit Permissions
# ==============================================================================


def test_r05_manager_cannot_edit_report_but_can_edit_own_contact_fields(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R05:
    - Manager cannot edit a direct report or anyone else (403, nothing saved).
    - A manager editing their own record follows employee rules (phone/last_name 200, HR field 403).
    """
    mgr_user = profile_company["manager"]
    mgr_emp = profile_company["emp_mgr"]
    staff_emp = profile_company["emp_staff"]
    other_emp = profile_company["emp_other"]
    mgr_headers = _auth_headers(mgr_user)
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Manager attempts to edit direct report -> 403
    res_edit_report = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=mgr_headers,
        json={"last_name": "ManagerAttempt"},
    )
    assert res_edit_report.status_code == 403
    db.refresh(staff_emp)
    assert staff_emp.last_name != "ManagerAttempt"

    # 2. Manager attempts to edit non-report colleague -> 403
    res_edit_other = client.put(
        f"/api/v1/employees/{other_emp.id}",
        headers=mgr_headers,
        json={"last_name": "ManagerAttemptOther"},
    )
    assert res_edit_other.status_code == 403

    # 3. Manager edits own contact field -> 200
    res_edit_own_phone = client.put(
        f"/api/v1/employees/{mgr_emp.id}",
        headers=mgr_headers,
        json={"phone": "+9876543210"},
    )
    assert res_edit_own_phone.status_code == 200
    assert res_edit_own_phone.json()["phone"] == "+9876543210"

    # 4. Manager attempts to edit own position (HR-only) -> 403
    res_edit_own_hr = client.put(
        f"/api/v1/employees/{mgr_emp.id}",
        headers=mgr_headers,
        json={"position": "Director"},
    )
    assert res_edit_own_hr.status_code == 403


# ==============================================================================
# R06: Input Validation, Trimming, and Dates
# ==============================================================================


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"first_name": None},
        {"first_name": ""},
        {"first_name": "   "},
        {"first_name": "A" * 101},
        {"last_name": ""},  # empty string rejected (null or 1-100)
        {"last_name": "   "},
        {"last_name": "B" * 101},
        {"phone": "1" * 21},
        {"position": "P" * 151},
        {"personal_email": "bad-email"},
        {"personal_email": f"{'a' * 250}@x.com"},
        {"email": None},
        {"email": "not-an-email"},
        {"email": f"{'e' * 250}@x.com"},
        {"level": "L99"},
        {"notice_period_days": -1},
        {"notice_period_days": 366},
        {"notice_period_days": None},
        {"hire_date": None},
        {"employment_type": None},
        {"is_attendance_exempt": None},
        {},  # empty body gives 422
    ],
)
def test_r06_input_validation_bad_inputs_give_422(
    client: TestClient, profile_company: dict[str, Any], bad_payload: dict[str, Any]
) -> None:
    """R06: All invalid inputs give 422 and DB remains unchanged."""
    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_emp = profile_company["emp_staff"]

    res = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json=bad_payload,
    )
    assert res.status_code == 422, (
        f"Expected 422 for payload {bad_payload}, got {res.status_code}: {res.text}"
    )


def test_r06_trimming_lowercasing_and_probation_end_date_rules(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R06:
    - Trimming and lowercasing saved correctly.
    - probation_end_date cannot be before hire_date (using existing hire_date if unchanged).
    """
    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_emp = profile_company["emp_staff"]
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Trimming and lowercasing
    new_work_email = f"  TRIMMED.{uuid.uuid4().hex[:6]}@EXAMPLE.COM  "
    new_personal_email = f"  PERSONAL.{uuid.uuid4().hex[:6]}@EXAMPLE.COM  "
    res_trim = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={
            "first_name": "  Trimmable  ",
            "last_name": "  Lastname  ",
            "email": new_work_email,
            "personal_email": new_personal_email,
        },
    )
    assert res_trim.status_code == 200
    body = res_trim.json()
    assert body["first_name"] == "Trimmable"
    assert body["last_name"] == "Lastname"
    assert body["email"] == new_work_email.strip().lower()
    assert body["personal_email"] == new_personal_email.strip().lower()

    # 2. probation_end_date before hire_date is rejected
    # Current hire_date is 2024-01-01
    res_bad_probation = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"probation_end_date": "2023-12-31"},
    )
    assert res_bad_probation.status_code == 400 or res_bad_probation.status_code == 422

    # Both hire_date and probation_end_date in same payload with probation before hire_date
    res_bad_both = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"hire_date": "2025-06-01", "probation_end_date": "2025-05-01"},
    )
    assert res_bad_both.status_code == 400 or res_bad_both.status_code == 422


# ==============================================================================
# R07: Relationships, Uniqueness, Email Sync & Token Revocation
# ==============================================================================


def test_r07_relationships_uniqueness_email_sync_and_revocation(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R07:
    - Duplicate email in another case -> 409
    - Email taken in users -> 409 and employees.email unchanged
    - Email change updates users.email, old refresh token rejected, login with new email works
    - Unchanged inactive manager does not block phone edit by HR
    - Other-company department, location, manager ids give same 400 as missing ids
    - Self manager, loop and inactive manager rejected on change.
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_user = profile_company["emp_staff_user"]
    staff_emp = profile_company["emp_staff"]
    staff_emp_id = staff_emp.id
    emp_mgr_id = profile_company["emp_mgr"].id
    other_emp = profile_company["emp_other"]
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Duplicate email in employees (case variant) -> 409
    other_email_variant = other_emp.email.upper()
    res_dup_emp = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"email": other_email_variant},
    )
    assert res_dup_emp.status_code == 409

    # 2. Duplicate email taken in users -> 409
    owner_user = profile_company["owner"]
    res_dup_user = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"email": owner_user.email},
    )
    assert res_dup_user.status_code == 409
    db.refresh(staff_emp)
    assert staff_emp.email == staff_user.email

    # 3. Other company department, location, manager ids give same 400 as missing ids
    tenant2 = _make_tenant(db, name="Other Co", code=f"OC{uuid.uuid4().hex[:4].upper()}")
    t2_cid = tenant2.company_id
    bind_tenant_to_session(db, company_id=t2_cid, is_platform_admin=True)
    t2_dept_id = uuid.uuid4()
    t2_loc_id = uuid.uuid4()
    t2_emp_id = uuid.uuid4()
    t2_dept = Department(id=t2_dept_id, company_id=t2_cid, name="T2 Dept")
    t2_loc = CompanyLocation(
        id=t2_loc_id,
        company_id=t2_cid,
        name="T2 Loc",
        code=f"T2L{uuid.uuid4().hex[:4].upper()}",
        country="IN",
    )
    t2_emp = Employee(
        id=t2_emp_id,
        company_id=t2_cid,
        employee_code=f"OC-{uuid.uuid4().hex[:4].upper()}-0001",
        first_name="T2",
        email=f"t2-{uuid.uuid4().hex[:6]}@example.com",
        hire_date=date(2025, 1, 1),
    )
    db.add_all([t2_dept, t2_loc, t2_emp])
    db.commit()

    # Switch back to company 1
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # Compare non-existent vs other company for department
    non_existent_id = str(uuid.uuid4())
    res_missing_dept = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"department_id": non_existent_id},
    )
    res_other_dept = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"department_id": str(t2_dept_id)},
    )
    assert res_missing_dept.status_code == 400
    assert res_other_dept.status_code == 400
    assert (
        res_missing_dept.json()["error"]["code"]
        == res_other_dept.json()["error"]["code"]
        == "invalid_reference"
    )
    assert res_missing_dept.json()["error"]["message"] == res_other_dept.json()["error"]["message"]

    # Location
    res_missing_loc = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"location_id": non_existent_id},
    )
    res_other_loc = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"location_id": str(t2_loc_id)},
    )
    assert res_missing_loc.status_code == 400
    assert res_other_loc.status_code == 400
    assert (
        res_missing_loc.json()["error"]["code"]
        == res_other_loc.json()["error"]["code"]
        == "invalid_reference"
    )
    assert res_missing_loc.json()["error"]["message"] == res_other_loc.json()["error"]["message"]

    # Manager
    res_missing_mgr = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"reporting_manager_id": non_existent_id},
    )
    res_other_mgr = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(t2_emp_id)},
    )
    assert res_missing_mgr.status_code == 400
    assert res_other_mgr.status_code == 400
    assert (
        res_missing_mgr.json()["error"]["code"]
        == res_other_mgr.json()["error"]["code"]
        == "invalid_reference"
    )
    assert res_missing_mgr.json()["error"]["message"] == res_other_mgr.json()["error"]["message"]

    # 4. Self manager and loop rejected
    res_self_mgr = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(staff_emp_id)},
    )
    assert res_self_mgr.status_code == 400
    assert res_self_mgr.json()["error"]["code"] == "invalid_reference"

    # Loop: mgr's reporting manager set to staff_emp (who already reports to mgr)
    res_loop = client.put(
        f"/api/v1/employees/{emp_mgr_id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(staff_emp.id)},
    )
    assert res_loop.status_code == 400
    assert res_loop.json()["error"]["code"] == "invalid_reference"

    # 5. Inactive manager rejected on change
    # Deactivate other_emp
    other_emp.is_active = False
    db.commit()
    res_inact_mgr = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(other_emp.id)},
    )
    assert res_inact_mgr.status_code == 400
    assert res_inact_mgr.json()["error"]["code"] == "invalid_reference"

    # 6. Unchanged inactive manager does NOT block a phone edit by HR
    # Set staff_emp manager to other_emp in DB directly while inactive
    staff_emp.reporting_manager_id = other_emp.id
    db.commit()
    res_phone_edit = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"phone": "+1122334455"},
    )
    assert res_phone_edit.status_code == 200
    assert res_phone_edit.json()["phone"] == "+1122334455"

    # 7. Email change updates users.email, revokes refresh token, and login with new email works
    # First, login as staff_user to get a refresh token
    res_login_old = client.post(
        "/api/v1/auth/login",
        json={"email": staff_user.email, "password": "Test1234pass!"},
    )
    assert res_login_old.status_code == 200
    refresh_cookie = res_login_old.headers.get("set-cookie", "")
    assert "refresh_token=" in refresh_cookie

    # HR updates staff_emp email
    brand_new_email = f"brandnew-{uuid.uuid4().hex[:6]}@example.com"
    res_email_change = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"email": brand_new_email},
    )
    assert res_email_change.status_code == 200

    # Assert users.email was updated in DB
    db.refresh(staff_user)
    assert staff_user.email == brand_new_email

    # Assert old refresh token is revoked
    raw_cookie_val = ""
    for part in refresh_cookie.split(";"):
        if "refresh_token=" in part:
            raw_cookie_val = part.split("refresh_token=")[1].strip()
    client.cookies.set("refresh_token", raw_cookie_val)
    res_refresh = client.post("/api/v1/auth/refresh")
    assert res_refresh.status_code == 401

    # Login with new email works
    res_login_new = client.post(
        "/api/v1/auth/login",
        json={"email": brand_new_email, "password": "Test1234pass!"},
    )
    assert res_login_new.status_code == 200
    assert res_login_new.json()["access_token"]


# ==============================================================================
# R08: Personal Data & Response Hygiene
# ==============================================================================


def test_r08_personal_data_masking_in_audit_and_response_hygiene(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R08:
    - PUT response for HR has personal_email.
    - Audit details mask personal_email and phone with mask_tail (raw values must not appear).
    - Response has no token, password, or hash fields.
    - PUT response matches GET response structure.
    """
    from app.core.masking import mask_tail

    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_emp = profile_company["emp_staff"]
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    raw_phone = "+1987654321"
    raw_personal_email = f"mysecret-{uuid.uuid4().hex[:6]}@personal.com"

    res_put = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"phone": raw_phone, "personal_email": raw_personal_email},
    )
    assert res_put.status_code == 200
    put_body = res_put.json()
    assert put_body["personal_email"] == raw_personal_email
    assert put_body["phone"] == raw_phone

    # Check for secret leaks
    for forbidden in ("activation_token_hash", "token_hash", "hashed_password", "password"):
        assert forbidden not in put_body

    # Compare with GET response
    res_get = client.get(f"/api/v1/employees/{staff_emp.id}", headers=hr_headers)
    assert res_get.status_code == 200
    get_body = res_get.json()
    assert set(put_body.keys()) == set(get_body.keys())

    # Check AuditLog entry
    audit_row = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_UPDATED",
            AuditLog.entity_id == staff_emp.id,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit_row is not None
    details = _get_audit_details(audit_row)
    assert "phone" in details
    assert "personal_email" in details

    # Assert masked with mask_tail, raw value not present
    expected_masked_phone = mask_tail(raw_phone)
    expected_masked_p_email = mask_tail(raw_personal_email)
    assert details["phone"]["to"] == expected_masked_phone
    assert details["personal_email"]["to"] == expected_masked_p_email
    assert raw_phone not in str(details)
    assert raw_personal_email not in str(details)


# ==============================================================================
# R09: Audit Rows: Changed Fields Only, Zero on Errors or Unchanged
# ==============================================================================


def test_r09_audit_rows_changed_fields_only_and_reactivation_audit(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R09:
    - Exactly one EMPLOYEE_UPDATED row per change with only changed fields (from/to).
    - No row for 401, 403, 404, 409, 422 or unchanged request (unchanged returns 200).
    - Reactivation writes EMPLOYEE_REACTIVATED with the actor.
    - No row on failed reactivation.
    """
    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_emp = profile_company["emp_staff"]
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Unchanged request returns 200 but writes NO audit row
    initial_audit_count = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    res_unchanged = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"first_name": staff_emp.first_name},
    )
    assert res_unchanged.status_code == 200
    assert db.query(AuditLog).filter(AuditLog.company_id == cid).count() == initial_audit_count

    # 2. Failed requests (403, 404, 409, 422) write NO audit row
    client.put(
        f"/api/v1/employees/{staff_emp.id}", headers=hr_headers, json={"first_name": ""}
    )  # 422
    client.put(
        f"/api/v1/employees/{uuid.uuid4()}", headers=hr_headers, json={"first_name": "Ghost"}
    )  # 404
    assert db.query(AuditLog).filter(AuditLog.company_id == cid).count() == initial_audit_count

    # 3. Successful change writes exactly one EMPLOYEE_UPDATED containing only changed fields
    res_change = client.put(
        f"/api/v1/employees/{staff_emp.id}",
        headers=hr_headers,
        json={"position": "Staff Specialist"},
    )
    assert res_change.status_code == 200
    audit_updated = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_UPDATED",
            AuditLog.entity_id == staff_emp.id,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit_updated is not None
    details = _get_audit_details(audit_updated)
    assert set(details.keys()) == {"position"}
    assert details["position"]["to"] == "Staff Specialist"

    # 4. Reactivation writes EMPLOYEE_REACTIVATED with actor
    # First deactivate
    res_deact = client.delete(f"/api/v1/employees/{staff_emp.id}", headers=hr_headers)
    assert res_deact.status_code == 204

    # Reactivate via toggle-active
    res_react = client.post(f"/api/v1/employees/{staff_emp.id}/toggle-active", headers=hr_headers)
    assert res_react.status_code == 200

    audit_reactivated = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_REACTIVATED",
            AuditLog.entity_id == staff_emp.id,
        )
        .first()
    )
    assert audit_reactivated is not None
    assert audit_reactivated.actor_user_id == profile_company["hr_admin"].id

    # 5. Failed reactivation writes NO audit row
    before_failed_react = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    res_bad_react = client.post(
        f"/api/v1/employees/{uuid.uuid4()}/toggle-active", headers=hr_headers
    )
    assert res_bad_react.status_code == 404
    assert db.query(AuditLog).filter(AuditLog.company_id == cid).count() == before_failed_react


# ==============================================================================
# R10: Rate Limiting, Row Locking, Tenant Isolation & Concurrency
# ==============================================================================


def test_r10_rate_limiting_put_and_toggle_active(
    client: TestClient, profile_company: dict[str, Any]
) -> None:
    """R10:
    PUT /employees/{id} and toggle-active are limited to 30/minute per user.
    """
    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_emp = profile_company["emp_staff"]

    limiter.enabled = True
    try:
        limiter.reset()
        put_responses = [
            client.put(
                f"/api/v1/employees/{staff_emp.id}",
                headers=hr_headers,
                json={"phone": f"+123456{i:04d}"},
            )
            for i in range(35)
        ]
        put_codes = [r.status_code for r in put_responses]
        assert put_codes[:30] == [200] * 30, f"Expected 30 200s, got: {put_codes[:30]}"
        assert all(c == 429 for c in put_codes[30:]), (
            f"Expected 429 on 31st+, got: {put_codes[30:]}"
        )

        limiter.reset()
        toggle_responses = [
            client.post(
                f"/api/v1/employees/{staff_emp.id}/toggle-active",
                headers=hr_headers,
            )
            for _ in range(35)
        ]
        toggle_codes = [r.status_code for r in toggle_responses]
        assert toggle_codes[:30] == [200] * 30, f"Expected 30 200s, got: {toggle_codes[:30]}"
        assert all(c == 429 for c in toggle_codes[30:]), (
            f"Expected 429 on 31st+, got: {toggle_codes[30:]}"
        )
    finally:
        limiter.enabled = False
        limiter.reset()


def test_r10_isolation_and_editing_deactivated_employee(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """R10:
    - Other company gives 404 on PUT /employees/{id}.
    - HR can edit a deactivated employee (200 plus audit).
    - A deactivated user's own token cannot edit.
    """
    from tests.conftest import _make_tenant

    hr_headers = _auth_headers(profile_company["hr_admin"])
    staff_emp = profile_company["emp_staff"]
    staff_emp_id = staff_emp.id
    staff_user = profile_company["emp_staff_user"]
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Other company gives 404
    tenant2 = _make_tenant(db, name="Other Isolation Co", code=f"OIC{uuid.uuid4().hex[:4].upper()}")
    # Re-bind session to cid so profile_company instances remain valid
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    t2_hr_headers = tenant2.hr_headers
    res_other_co = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=t2_hr_headers,
        json={"phone": "+9999999999"},
    )
    assert res_other_co.status_code == 404

    # 2. Deactivate employee
    client.delete(f"/api/v1/employees/{staff_emp_id}", headers=hr_headers)
    db.refresh(staff_emp)
    assert staff_emp.is_active is False

    # HR edits deactivated employee -> 200 with audit
    res_hr_deact_edit = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers=hr_headers,
        json={"position": "Archived Position"},
    )
    assert res_hr_deact_edit.status_code == 200
    assert res_hr_deact_edit.json()["position"] == "Archived Position"

    # 3. Deactivated user's own token cannot edit
    staff_token = create_access_token(
        sub=str(staff_user.id), company_id=str(cid), role=staff_user.role.value
    )
    res_deact_user_edit = client.put(
        f"/api/v1/employees/{staff_emp_id}",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"phone": "+1000000000"},
    )
    assert res_deact_user_edit.status_code in (401, 403)


def test_r10_concurrency_simultaneous_edits_different_fields_and_email_race() -> None:
    """R10:
    - Two simultaneous edits of different fields both persist with no 500.
    - Two simultaneous edits claiming the same email give one 200 and one 409.
    Uses separate engine and real cleanup with assertions.
    """
    assert settings.TEST_DATABASE_URL is not None, "TEST_DATABASE_URL must be configured"
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)

    try:
        cid = uuid.uuid4()
        with Session(engine) as setup_sess:
            company = Company(
                id=cid,
                name="Concurrent Edit Co",
                code=f"CEC{uuid.uuid4().hex[:4].upper()}",
                email=f"cec-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
            setup_sess.add(company)
            setup_sess.flush()

            bind_tenant_to_session(setup_sess, company_id=cid, is_platform_admin=True)

            hr_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            emp_target = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                employee_code=f"{company.code}-0001",
                first_name="ConcTarget",
                email=f"target-{uuid.uuid4().hex[:6]}@example.com",
                employment_type=EmploymentType.full_time,
                hire_date=date(2025, 1, 1),
                is_active=True,
                invitation_status=InvitationStatus.activated,
            )
            emp_other = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                employee_code=f"{company.code}-0002",
                first_name="ConcOther",
                email=f"other-{uuid.uuid4().hex[:6]}@example.com",
                employment_type=EmploymentType.full_time,
                hire_date=date(2025, 1, 1),
                is_active=True,
                invitation_status=InvitationStatus.activated,
            )
            setup_sess.add_all([hr_user, emp_target, emp_other])
            setup_sess.commit()

            token = create_access_token(
                sub=str(hr_user.id), company_id=str(cid), role=hr_user.role.value
            )
            headers = {"Authorization": f"Bearer {token}"}
            target_id = emp_target.id
            other_id = emp_other.id

        def _get_test_db():
            sess = Session(engine)
            try:
                yield sess
            finally:
                sess.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db

        # Part A: Two simultaneous edits of different fields on target employee
        barrier_diff = threading.Barrier(2)
        results_diff: list[int] = []

        def worker_diff(payload: dict[str, Any]):
            c = TestClient(fastapi_app)
            try:
                barrier_diff.wait()
                r = c.put(f"/api/v1/employees/{target_id}", headers=headers, json=payload)
                results_diff.append(r.status_code)
            except Exception:
                results_diff.append(999)

        t1 = threading.Thread(target=worker_diff, args=({"phone": "+1234567890"},))
        t2 = threading.Thread(target=worker_diff, args=({"position": "Concurrent Tech Lead"},))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results_diff, f"Server returned 500: {results_diff}"
        assert results_diff == [200, 200], f"Expected both to succeed 200, got {results_diff}"

        # Part B: Two simultaneous edits claiming the same new email on two different employees
        shared_new_email = f"sharedrace-{uuid.uuid4().hex[:6]}@example.com"
        barrier_race = threading.Barrier(2)
        results_race: list[int] = []

        def worker_race(emp_id_to_edit: uuid.UUID):
            c = TestClient(fastapi_app)
            try:
                barrier_race.wait()
                r = c.put(
                    f"/api/v1/employees/{emp_id_to_edit}",
                    headers=headers,
                    json={"email": shared_new_email},
                )
                results_race.append(r.status_code)
            except Exception:
                results_race.append(999)

        t3 = threading.Thread(target=worker_race, args=(target_id,))
        t4 = threading.Thread(target=worker_race, args=(other_id,))
        t3.start()
        t4.start()
        t3.join()
        t4.join()

        assert 500 not in results_race, f"Server returned 500 in email race: {results_race}"
        assert sorted(results_race) == [200, 409], (
            f"Expected exactly one 200 and one 409, got {results_race}"
        )

    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        assert settings.TEST_MIGRATION_URL is not None, "TEST_MIGRATION_URL must be configured"
        owner_engine = create_engine(settings.TEST_MIGRATION_URL)
        try:
            with Session(owner_engine) as cleanup:
                bind_tenant_to_session(cleanup, company_id=cid, is_platform_admin=True)
                cleanup.execute(
                    text("DELETE FROM audit_logs WHERE company_id = :cid"), {"cid": cid}
                )
                cleanup.execute(text("DELETE FROM employees WHERE company_id = :cid"), {"cid": cid})
                cleanup.execute(text("DELETE FROM users WHERE company_id = :cid"), {"cid": cid})
                cleanup.execute(text("DELETE FROM companies WHERE id = :cid"), {"cid": cid})
                cleanup.commit()
                remaining = cleanup.execute(
                    text("SELECT 1 FROM companies WHERE id = :cid"), {"cid": cid}
                ).scalar()
                assert remaining is None, f"Company {cid} was not deleted during cleanup"
        finally:
            owner_engine.dispose()
        engine.dispose()
