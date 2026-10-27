import threading
import uuid
from datetime import date, timedelta
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
from app.modules.hr.models import (
    Department,
    Employee,
    EmploymentType,
    InvitationStatus,
)
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
        name=f"Sections Corp {uuid.uuid4().hex[:6]}",
        code=f"SC{uuid.uuid4().hex[:4].upper()}",
        email=f"sections-{uuid.uuid4().hex[:6]}@example.com",
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
        "department": dept,
        "location": loc,
    }


VALID_SAMPLES = {
    "addresses": {
        "kind": "current",
        "line1": "123 Main St",
        "line2": "Apt 4B",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "country": "India",
    },
    "emergency-contacts": {
        "name": "Jane Doe",
        "relationship": "Spouse",
        "phone": "+91-9876543210",
        "alt_phone": "(080) 12345678",
        "email": "jane.doe@example.com",
    },
    "skills": {
        "name": "Python",
        "level": "intermediate",
        "years_experience": 5,
    },
    "education": {
        "institution": "National Institute of Tech",
        "degree": "B.Tech Computer Science",
        "field_of_study": "Information Technology",
        "start_date": "2018-08-01",
        "end_date": "2022-05-30",
        "grade": "8.5 CGPA",
    },
    "experience": {
        "employer": "Tech Global Solutions",
        "job_title": "Software Engineer",
        "start_date": "2022-06-01",
        "end_date": "2023-12-31",
        "description": "Backend API development",
    },
}

SECTIONS = ["addresses", "emergency-contacts", "skills", "education", "experience"]


# ==============================================================================
# R1 / R2: Employee CRUD on own entries; Colleague 403; No Token 401; Deactivated 403
# ==============================================================================


@pytest.mark.parametrize("section", SECTIONS)
def test_r01_r02_employee_full_crud_own_and_access_control(
    client: TestClient, profile_company: dict[str, Any], db: Session, section: str
) -> None:
    staff_emp = profile_company["emp_staff"]
    other_emp = profile_company["emp_other"]
    staff_headers = _auth_headers(profile_company["emp_staff_user"])
    payload = VALID_SAMPLES[section]

    # 1. No token -> 401
    res_no_token = client.post(f"/api/v1/employees/{staff_emp.id}/{section}", json=payload)
    assert res_no_token.status_code == 401

    # 2. Colleague attempts create -> 403
    res_colleague = client.post(
        f"/api/v1/employees/{other_emp.id}/{section}",
        headers=staff_headers,
        json=payload,
    )
    assert res_colleague.status_code == 403

    # 3. Own active record create -> 201
    res_create = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
        json=payload,
    )
    assert res_create.status_code == 201
    created_entry = res_create.json()
    entry_id = created_entry["id"]
    assert entry_id

    # 4. GET list on own record -> 200
    res_list = client.get(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
    )
    assert res_list.status_code == 200
    entries = res_list.json()
    assert any(e["id"] == entry_id for e in entries)

    # 5. Colleague attempts GET -> 403
    res_colleague_get = client.get(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=_auth_headers(profile_company["emp_other_user"]),
    )
    assert res_colleague_get.status_code == 403

    # 6. Colleague attempts PUT -> 403
    update_payload = (
        {"city": "Mysore"}
        if section == "addresses"
        else {"name": "Senior Jane"}
        if section == "emergency-contacts"
        else {"years_experience": 6}
        if section == "skills"
        else {"grade": "9.0 CGPA"}
        if section == "education"
        else {"job_title": "Lead Software Engineer"}
    )
    res_colleague_put = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=_auth_headers(profile_company["emp_other_user"]),
        json=update_payload,
    )
    assert res_colleague_put.status_code == 403

    # 7. Own record PUT -> 200
    res_update = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
        json=update_payload,
    )
    assert res_update.status_code == 200

    # 8. Own deactivated record -> 403 for writes and reads
    staff_emp.is_active = False
    db.commit()

    res_deact_get = client.get(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
    )
    assert res_deact_get.status_code == 403

    res_deact_put = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
        json=update_payload,
    )
    assert res_deact_put.status_code == 403

    # Restore active state
    staff_emp.is_active = True
    db.commit()

    # 9. Own record DELETE -> 204
    res_delete = client.delete(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
    )
    assert res_delete.status_code == 204

    # Confirm deleted
    res_get_after = client.get(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
    )
    assert not any(e["id"] == entry_id for e in res_get_after.json())


# ==============================================================================
# R3: Education & Experience Verification
# ==============================================================================


@pytest.mark.parametrize("section", ["education", "experience"])
def test_r03_verification_lifecycle_and_reset_on_employee_edit(
    client: TestClient, profile_company: dict[str, Any], db: Session, section: str
) -> None:
    staff_emp = profile_company["emp_staff"]
    staff_headers = _auth_headers(profile_company["emp_staff_user"])
    hr_headers = _auth_headers(profile_company["hr_admin"])
    owner_headers = _auth_headers(profile_company["owner"])
    payload = VALID_SAMPLES[section]

    # 1. New entry starts unverified
    res_create = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
        json=payload,
    )
    assert res_create.status_code == 201
    entry = res_create.json()
    entry_id = entry["id"]
    assert entry["verification_status"] == "unverified"
    assert entry.get("verified_by") is None
    assert entry.get("verified_at") is None

    # 2. Employee cannot verify or unverify -> 403
    res_emp_verify = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/verify",
        headers=staff_headers,
    )
    assert res_emp_verify.status_code == 403

    res_emp_unverify = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/unverify",
        headers=staff_headers,
    )
    assert res_emp_unverify.status_code == 403

    # 3. HR Admin verifies -> 200, status=verified
    res_hr_verify = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/verify",
        headers=hr_headers,
    )
    assert res_hr_verify.status_code == 200
    v_entry = res_hr_verify.json()
    assert v_entry["verification_status"] == "verified"
    assert v_entry["verified_by"] == str(profile_company["hr_admin"].id)
    assert v_entry["verified_at"] is not None

    # Verify is idempotent: calling again changes nothing and writes no second audit row
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    audit_count_before = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "EMPLOYEE_ENTRY_VERIFIED")
        .count()
    )
    res_hr_verify_again = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/verify",
        headers=hr_headers,
    )
    assert res_hr_verify_again.status_code == 200
    audit_count_after = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.action == "EMPLOYEE_ENTRY_VERIFIED")
        .count()
    )
    assert audit_count_after == audit_count_before

    # 4. HR edit keeps verification status intact
    edit_key = "grade" if section == "education" else "description"
    res_hr_edit = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=hr_headers,
        json={edit_key: "Top Honors"},
    )
    assert res_hr_edit.status_code == 200
    assert res_hr_edit.json()["verification_status"] == "verified"

    # 5. Employee NO-OP edit does NOT reset verification
    res_noop_edit = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
        json={edit_key: "Top Honors"},
    )
    assert res_noop_edit.status_code == 200
    assert res_noop_edit.json()["verification_status"] == "verified"

    # 6. Employee REAL edit resets verification status, verified_by, verified_at
    res_emp_real_edit = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
        json={edit_key: "Modified by Employee"},
    )
    assert res_emp_real_edit.status_code == 200
    reset_entry = res_emp_real_edit.json()
    assert reset_entry["verification_status"] == "unverified"
    assert reset_entry.get("verified_by") is None
    assert reset_entry.get("verified_at") is None

    # 7. Owner can verify and unverify
    res_owner_verify = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/verify",
        headers=owner_headers,
    )
    assert res_owner_verify.status_code == 200
    assert res_owner_verify.json()["verification_status"] == "verified"

    res_owner_unverify = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/unverify",
        headers=owner_headers,
    )
    assert res_owner_unverify.status_code == 200
    assert res_owner_unverify.json()["verification_status"] == "unverified"

    # 8. Delete of verified entry by employee owner is allowed and returns 204
    client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}/verify",
        headers=hr_headers,
    )
    res_del_verified = client.delete(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
    )
    assert res_del_verified.status_code == 204


# ==============================================================================
# R4: HR and Owner Full CRUD; Injection of Protected Fields Rejected (422)
# ==============================================================================


@pytest.mark.parametrize("section", SECTIONS)
def test_r04_hr_owner_crud_and_protected_fields_rejected(
    client: TestClient, profile_company: dict[str, Any], section: str
) -> None:
    staff_emp = profile_company["emp_staff"]
    hr_headers = _auth_headers(profile_company["hr_admin"])
    owner_headers = _auth_headers(profile_company["owner"])
    payload = VALID_SAMPLES[section]

    # 1. HR admin and Owner create
    res_hr_create = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=hr_headers,
        json=payload,
    )
    assert res_hr_create.status_code == 201
    entry_id = res_hr_create.json()["id"]

    # 2. Protected fields rejected on POST and PUT with 422
    protected_cases = [
        {"id": str(uuid.uuid4())},
        {"employee_id": str(uuid.uuid4())},
        {"company_id": str(uuid.uuid4())},
        {"verification_status": "verified"},
        {"verified_by": str(uuid.uuid4())},
        {"verified_at": "2026-01-01T00:00:00Z"},
    ]
    for prot in protected_cases:
        res_bad_post = client.post(
            f"/api/v1/employees/{staff_emp.id}/{section}",
            headers=hr_headers,
            json={**payload, **prot},
        )
        assert res_bad_post.status_code == 422, f"Expected 422 for {prot} on POST {section}"

        res_bad_put = client.put(
            f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
            headers=hr_headers,
            json=prot,
        )
        assert res_bad_put.status_code == 422, f"Expected 422 for {prot} on PUT {section}"

    update_payload = (
        {"city": "New Delhi"}
        if section == "addresses"
        else {"name": "Updated Name"}
        if section == "emergency-contacts"
        else {"years_experience": 8}
        if section == "skills"
        else {"grade": "Distinction"}
        if section == "education"
        else {"job_title": "Principal Architect"}
    )

    # 4. Cross-employee protection: HR cannot edit/delete staff_emp's entry
    # via other_emp's path -> 404
    other_emp = profile_company["emp_other"]
    res_cross_put = client.put(
        f"/api/v1/employees/{other_emp.id}/{section}/{entry_id}",
        headers=hr_headers,
        json=update_payload,
    )
    assert res_cross_put.status_code == 404, f"Cross-employee PUT should return 404 for {section}"

    res_cross_del = client.delete(
        f"/api/v1/employees/{other_emp.id}/{section}/{entry_id}",
        headers=hr_headers,
    )
    assert res_cross_del.status_code == 404, (
        f"Cross-employee DELETE should return 404 for {section}"
    )

    # 5. Owner can update and delete
    res_owner_put = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=owner_headers,
        json=update_payload,
    )
    assert res_owner_put.status_code == 200

    res_owner_del = client.delete(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=owner_headers,
    )
    assert res_owner_del.status_code == 204


# ==============================================================================
# R5: Manager Scoping Rules
# ==============================================================================


def test_r05_manager_scoping_rules(client: TestClient, profile_company: dict[str, Any]) -> None:
    """Manager GET skills of direct report -> 200.
    Manager GET skills of non-report -> 403.
    Manager GET other 4 sections of direct report -> 403.
    Manager write on direct report in any section -> 403.
    Manager own record behaves as employee (can read & write own entries in all sections).
    """
    mgr_emp = profile_company["emp_mgr"]
    staff_emp = profile_company["emp_staff"]  # direct report of mgr_emp
    other_emp = profile_company["emp_other"]  # NOT a direct report
    mgr_headers = _auth_headers(profile_company["manager"])
    hr_headers = _auth_headers(profile_company["hr_admin"])

    # Seed an entry in all 5 sections for staff_emp
    seed_entries: dict[str, str] = {}
    for sec in SECTIONS:
        r = client.post(
            f"/api/v1/employees/{staff_emp.id}/{sec}",
            headers=hr_headers,
            json=VALID_SAMPLES[sec],
        )
        assert r.status_code == 201
        seed_entries[sec] = r.json()["id"]

    # 1. Manager GET skills of direct report -> 200
    res_mgr_skills = client.get(
        f"/api/v1/employees/{staff_emp.id}/skills",
        headers=mgr_headers,
    )
    assert res_mgr_skills.status_code == 200

    # 2. Manager GET skills of non-report -> 403
    res_non_report_skills = client.get(
        f"/api/v1/employees/{other_emp.id}/skills",
        headers=mgr_headers,
    )
    assert res_non_report_skills.status_code == 403

    # 3. Manager GET other 4 sections of direct report -> 403
    for sec in ["addresses", "emergency-contacts", "education", "experience"]:
        res_sec = client.get(
            f"/api/v1/employees/{staff_emp.id}/{sec}",
            headers=mgr_headers,
        )
        assert res_sec.status_code == 403, f"Manager should get 403 on {sec} of report"

    # 4. Manager write on direct report in every section -> 403
    for sec in SECTIONS:
        # POST
        res_write_post = client.post(
            f"/api/v1/employees/{staff_emp.id}/{sec}",
            headers=mgr_headers,
            json=VALID_SAMPLES[sec],
        )
        assert res_write_post.status_code == 403, f"Manager should get 403 on POST {sec}"

        # PUT
        entry_id = seed_entries[sec]
        res_write_put = client.put(
            f"/api/v1/employees/{staff_emp.id}/{sec}/{entry_id}",
            headers=mgr_headers,
            json=VALID_SAMPLES[sec],
        )
        assert res_write_put.status_code == 403, f"Manager should get 403 on PUT {sec}"

        # DELETE
        res_write_del = client.delete(
            f"/api/v1/employees/{staff_emp.id}/{sec}/{entry_id}",
            headers=mgr_headers,
        )
        assert res_write_del.status_code == 403, f"Manager should get 403 on DELETE {sec}"

    # 5. Manager's own record follows employee rules (CRUD works on all sections)
    for sec in SECTIONS:
        res_own_post = client.post(
            f"/api/v1/employees/{mgr_emp.id}/{sec}",
            headers=mgr_headers,
            json=VALID_SAMPLES[sec],
        )
        assert res_own_post.status_code == 201
        m_entry_id = res_own_post.json()["id"]

        res_own_get = client.get(
            f"/api/v1/employees/{mgr_emp.id}/{sec}",
            headers=mgr_headers,
        )
        assert res_own_get.status_code == 200

        res_own_del = client.delete(
            f"/api/v1/employees/{mgr_emp.id}/{sec}/{m_entry_id}",
            headers=mgr_headers,
        )
        assert res_own_del.status_code == 204


# ==============================================================================
# R6: Input Validation, Caps, Trimming, and Concurrency
# ==============================================================================


BAD_POST_CASES = [
    ("addr_empty", "addresses", {}),
    ("addr_unknown", "addresses", {"unknown_field": "val"}),
    ("addr_null_required", "addresses", {**VALID_SAMPLES["addresses"], "line1": None}),
    ("addr_overlong", "addresses", {**VALID_SAMPLES["addresses"], "line1": "A" * 201}),
    ("addr_bad_kind", "addresses", {**VALID_SAMPLES["addresses"], "kind": "vacation"}),
    ("emg_empty", "emergency-contacts", {}),
    ("emg_unknown", "emergency-contacts", {"unknown_field": "val"}),
    (
        "emg_null_required_name",
        "emergency-contacts",
        {**VALID_SAMPLES["emergency-contacts"], "name": None},
    ),
    (
        "emg_null_required_rel",
        "emergency-contacts",
        {**VALID_SAMPLES["emergency-contacts"], "relationship": None},
    ),
    (
        "emg_null_required_phone",
        "emergency-contacts",
        {**VALID_SAMPLES["emergency-contacts"], "phone": None},
    ),
    (
        "emg_bad_phone",
        "emergency-contacts",
        {**VALID_SAMPLES["emergency-contacts"], "phone": "123-abc-789"},
    ),
    (
        "emg_overlong_name",
        "emergency-contacts",
        {**VALID_SAMPLES["emergency-contacts"], "name": "A" * 101},
    ),
    ("skill_empty", "skills", {}),
    ("skill_unknown", "skills", {"unknown_field": "val"}),
    ("skill_null_required", "skills", {**VALID_SAMPLES["skills"], "name": None}),
    ("skill_bad_level", "skills", {**VALID_SAMPLES["skills"], "level": "super_expert"}),
    ("skill_years_gt_60", "skills", {**VALID_SAMPLES["skills"], "years_experience": 61}),
    ("skill_overlong_name", "skills", {**VALID_SAMPLES["skills"], "name": "A" * 81}),
    ("edu_empty", "education", {}),
    ("edu_unknown", "education", {"unknown_field": "val"}),
    ("edu_null_required_inst", "education", {**VALID_SAMPLES["education"], "institution": None}),
    ("edu_null_required_deg", "education", {**VALID_SAMPLES["education"], "degree": None}),
    ("edu_null_required_start", "education", {**VALID_SAMPLES["education"], "start_date": None}),
    (
        "edu_future_start",
        "education",
        {
            **VALID_SAMPLES["education"],
            "start_date": (date.today() + timedelta(days=2)).isoformat(),
        },
    ),
    (
        "edu_end_before_start",
        "education",
        {**VALID_SAMPLES["education"], "start_date": "2022-01-01", "end_date": "2021-01-01"},
    ),
    (
        "edu_future_end",
        "education",
        {**VALID_SAMPLES["education"], "end_date": (date.today() + timedelta(days=5)).isoformat()},
    ),
    ("edu_overlong_inst", "education", {**VALID_SAMPLES["education"], "institution": "A" * 151}),
    ("exp_empty", "experience", {}),
    ("exp_unknown", "experience", {"unknown_field": "val"}),
    ("exp_null_required_emp", "experience", {**VALID_SAMPLES["experience"], "employer": None}),
    ("exp_null_required_title", "experience", {**VALID_SAMPLES["experience"], "job_title": None}),
    ("exp_null_required_start", "experience", {**VALID_SAMPLES["experience"], "start_date": None}),
    (
        "exp_future_start",
        "experience",
        {
            **VALID_SAMPLES["experience"],
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    ),
    (
        "exp_end_before_start",
        "experience",
        {**VALID_SAMPLES["experience"], "start_date": "2023-01-01", "end_date": "2022-01-01"},
    ),
    (
        "exp_future_end",
        "experience",
        {**VALID_SAMPLES["experience"], "end_date": (date.today() + timedelta(days=5)).isoformat()},
    ),
    ("exp_overlong_employer", "experience", {**VALID_SAMPLES["experience"], "employer": "A" * 151}),
]


@pytest.mark.parametrize("case_id,section,bad_body", BAD_POST_CASES)
def test_r06_post_bad_inputs_give_422(
    client: TestClient,
    profile_company: dict[str, Any],
    case_id: str,
    section: str,
    bad_body: dict[str, Any],
) -> None:
    staff_emp = profile_company["emp_staff"]
    staff_headers = _auth_headers(profile_company["emp_staff_user"])

    res = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
        json=bad_body,
    )
    assert res.status_code == 422, f"[{case_id}] Expected 422 on POST {section}: {bad_body}"


BAD_PUT_CASES = [
    ("put_addr_empty", "addresses", {}),
    ("put_addr_unknown", "addresses", {"random_extra": "value"}),
    ("put_addr_null_required", "addresses", {"line1": None}),
    ("put_addr_overlong", "addresses", {"line1": "A" * 201}),
    ("put_emg_empty", "emergency-contacts", {}),
    ("put_emg_unknown", "emergency-contacts", {"random_extra": "value"}),
    ("put_emg_null_required", "emergency-contacts", {"name": None}),
    ("put_emg_overlong", "emergency-contacts", {"name": "A" * 101}),
    ("put_skill_empty", "skills", {}),
    ("put_skill_unknown", "skills", {"random_extra": "value"}),
    ("put_skill_null_required", "skills", {"name": None}),
    ("put_skill_overlong", "skills", {"name": "A" * 81}),
    ("put_edu_empty", "education", {}),
    ("put_edu_unknown", "education", {"random_extra": "value"}),
    ("put_edu_null_required", "education", {"institution": None}),
    ("put_edu_overlong", "education", {"institution": "A" * 151}),
    ("put_exp_empty", "experience", {}),
    ("put_exp_unknown", "experience", {"random_extra": "value"}),
    ("put_exp_null_required", "experience", {"employer": None}),
    ("put_exp_overlong", "experience", {"employer": "A" * 151}),
]


@pytest.mark.parametrize("case_id,section,bad_body", BAD_PUT_CASES)
def test_r06_put_bad_inputs_give_422(
    client: TestClient,
    profile_company: dict[str, Any],
    case_id: str,
    section: str,
    bad_body: dict[str, Any],
) -> None:
    staff_emp = profile_company["emp_staff"]
    staff_headers = _auth_headers(profile_company["emp_staff_user"])

    # First create a valid entry
    res_c = client.post(
        f"/api/v1/employees/{staff_emp.id}/{section}",
        headers=staff_headers,
        json=VALID_SAMPLES[section],
    )
    assert res_c.status_code == 201
    entry_id = res_c.json()["id"]

    res_put = client.put(
        f"/api/v1/employees/{staff_emp.id}/{section}/{entry_id}",
        headers=staff_headers,
        json=bad_body,
    )
    assert res_put.status_code == 422, f"[{case_id}] Expected 422 on PUT {section}: {bad_body}"


def test_r06_uniqueness_and_entry_caps(client: TestClient, profile_company: dict[str, Any]) -> None:
    staff_emp = profile_company["emp_staff"]
    staff_headers = _auth_headers(profile_company["emp_staff_user"])

    # 1. Duplicate skill name (ignoring case) -> 409
    res_skill1 = client.post(
        f"/api/v1/employees/{staff_emp.id}/skills",
        headers=staff_headers,
        json={"name": "PostgreSQL", "level": "intermediate"},
    )
    assert res_skill1.status_code == 201

    res_skill_dup = client.post(
        f"/api/v1/employees/{staff_emp.id}/skills",
        headers=staff_headers,
        json={"name": "  postgresql  ", "level": "expert"},
    )
    assert res_skill_dup.status_code == 409

    # 2. Second address of same kind -> 409
    res_addr1 = client.post(
        f"/api/v1/employees/{staff_emp.id}/addresses",
        headers=staff_headers,
        json={**VALID_SAMPLES["addresses"], "kind": "current"},
    )
    assert res_addr1.status_code == 201

    res_addr_dup = client.post(
        f"/api/v1/employees/{staff_emp.id}/addresses",
        headers=staff_headers,
        json={**VALID_SAMPLES["addresses"], "kind": "current", "line1": "999 Second St"},
    )
    assert res_addr_dup.status_code == 409

    # 3. Text trimming on all string fields
    res_trim_skill = client.post(
        f"/api/v1/employees/{staff_emp.id}/skills",
        headers=staff_headers,
        json={"name": "   FastAPI   ", "level": "expert"},
    )
    assert res_trim_skill.status_code == 201
    assert res_trim_skill.json()["name"] == "FastAPI"

    res_trim_addr = client.post(
        f"/api/v1/employees/{staff_emp.id}/addresses",
        headers=staff_headers,
        json={
            "kind": "permanent",
            "line1": "   456 Elm St   ",
            "city": "   Bengaluru   ",
            "state": "   Karnataka   ",
            "postal_code": "   560002   ",
            "country": "   India   ",
        },
    )
    assert res_trim_addr.status_code == 201
    addr_body = res_trim_addr.json()
    assert addr_body["line1"] == "456 Elm St"
    assert addr_body["city"] == "Bengaluru"
    assert addr_body["state"] == "Karnataka"
    assert addr_body["postal_code"] == "560002"
    assert addr_body["country"] == "India"

    # 4. Max 20 entries cap (409 on 21st entry)
    # Add 18 more skills to reach 20 (already have 2: PostgreSQL, FastAPI)
    for i in range(18):
        r = client.post(
            f"/api/v1/employees/{staff_emp.id}/skills",
            headers=staff_headers,
            json={"name": f"Skill-{i:03d}", "level": "beginner"},
        )
        assert r.status_code == 201

    # 21st skill must give 409
    res_21st = client.post(
        f"/api/v1/employees/{staff_emp.id}/skills",
        headers=staff_headers,
        json={"name": "OverflowSkill", "level": "beginner"},
    )
    assert res_21st.status_code == 409


def test_r06_concurrency_race_for_max_20_entries(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """When 19 entries exist, two simultaneous POST requests result in exactly
    one 201 and one 409, final count is exactly 20, and never 500.
    Uses separate engine and real concurrency with barrier.
    """
    assert settings.TEST_DATABASE_URL is not None, "TEST_DATABASE_URL must be configured"
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)

    try:
        cid = uuid.uuid4()
        with Session(engine) as setup_sess:
            company = Company(
                id=cid,
                name="Concurrent Co",
                code=f"CONC{uuid.uuid4().hex[:4].upper()}",
                email=f"conc-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
            setup_sess.add(company)
            setup_sess.flush()

            bind_tenant_to_session(setup_sess, company_id=cid, is_platform_admin=True)

            staff_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"concstaff-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.employee,
                is_active=True,
            )
            setup_sess.add(staff_user)
            setup_sess.flush()

            staff_emp = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                user_id=staff_user.id,
                employee_code=f"{company.code}-0001",
                first_name="ConcStaff",
                email=staff_user.email,
                employment_type=EmploymentType.full_time,
                hire_date=date(2025, 1, 1),
                is_active=True,
                invitation_status=InvitationStatus.activated,
            )
            setup_sess.add(staff_emp)
            setup_sess.commit()

            token = create_access_token(
                sub=str(staff_user.id), company_id=str(cid), role=staff_user.role.value
            )
            headers = {"Authorization": f"Bearer {token}"}
            emp_id = staff_emp.id

        def _get_test_db():
            sess = Session(engine)
            try:
                yield sess
            finally:
                sess.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db

        # Create 19 education entries
        for i in range(19):
            r = client.post(
                f"/api/v1/employees/{emp_id}/education",
                headers=headers,
                json={
                    "institution": f"University {i}",
                    "degree": "BSc",
                    "start_date": "2015-01-01",
                    "end_date": "2019-01-01",
                },
            )
            assert r.status_code == 201

        barrier = threading.Barrier(2)
        results_concurrency: list[int] = []

        def post_worker(idx: int) -> None:
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                r = c.post(
                    f"/api/v1/employees/{emp_id}/education",
                    headers=headers,
                    json={
                        "institution": f"Concurrent Uni {idx}",
                        "degree": "MSc",
                        "start_date": "2020-01-01",
                        "end_date": "2022-01-01",
                    },
                )
                results_concurrency.append(r.status_code)
            except Exception:
                results_concurrency.append(999)

        t1 = threading.Thread(target=post_worker, args=(1,))
        t2 = threading.Thread(target=post_worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results_concurrency, f"Got 500 in concurrency race: {results_concurrency}"
        assert sorted(results_concurrency) == [201, 409], (
            f"Expected exactly one 201 and one 409, got: {results_concurrency}"
        )

        # Check total count in list
        res_list = client.get(
            f"/api/v1/employees/{emp_id}/education",
            headers=headers,
        )
        assert len(res_list.json()) == 20
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()


# ==============================================================================
# R7: Manager Anti-Cycle and Self Check (Test Gap from Part 1)
# ==============================================================================


def test_r07_manager_cannot_be_self_and_no_manager_loops(
    client: TestClient, profile_company: dict[str, Any]
) -> None:
    hr_headers = _auth_headers(profile_company["hr_admin"])
    emp1 = profile_company["emp_mgr"]
    emp2 = profile_company["emp_staff"]
    emp3 = profile_company["emp_other"]

    # 1. Manager cannot be set to self -> 400
    res_self = client.put(
        f"/api/v1/employees/{emp1.id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(emp1.id)},
    )
    assert res_self.status_code == 400

    # 2. Two-step loop: A under B then B under A -> 400
    # Currently emp2 reports to emp1. Attempt to set emp1's manager to emp2:
    res_loop2 = client.put(
        f"/api/v1/employees/{emp1.id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(emp2.id)},
    )
    assert res_loop2.status_code == 400

    # 3. Three-step loop: emp3 reports to emp2 (emp2 reports to emp1).
    # Setting emp1 to report to emp3 would create emp1 -> emp3 -> emp2 -> emp1.
    res_set_emp3 = client.put(
        f"/api/v1/employees/{emp3.id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(emp2.id)},
    )
    assert res_set_emp3.status_code == 200

    res_loop3 = client.put(
        f"/api/v1/employees/{emp1.id}",
        headers=hr_headers,
        json={"reporting_manager_id": str(emp3.id)},
    )
    assert res_loop3.status_code == 400


# ==============================================================================
# R8: Personal Data & Response Hygiene
# ==============================================================================


def test_r08_personal_data_masking_and_response_hygiene(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    staff_emp = profile_company["emp_staff"]
    hr_headers = _auth_headers(profile_company["hr_admin"])
    mgr_headers = _auth_headers(profile_company["manager"])
    other_headers = _auth_headers(profile_company["emp_other_user"])
    cid = profile_company["company"].id

    # 1. Address & emergency contacts created
    client.post(
        f"/api/v1/employees/{staff_emp.id}/addresses",
        headers=hr_headers,
        json=VALID_SAMPLES["addresses"],
    )
    client.post(
        f"/api/v1/employees/{staff_emp.id}/emergency-contacts",
        headers=hr_headers,
        json=VALID_SAMPLES["emergency-contacts"],
    )

    # 2. Manager and Colleague cannot access address or emergency-contacts
    for sec in ["addresses", "emergency-contacts"]:
        assert (
            client.get(f"/api/v1/employees/{staff_emp.id}/{sec}", headers=mgr_headers).status_code
            == 403
        )
        assert (
            client.get(f"/api/v1/employees/{staff_emp.id}/{sec}", headers=other_headers).status_code
            == 403
        )

    # 3. Employee response keys contain NO PAN field
    res_get_emp = client.get(f"/api/v1/employees/{staff_emp.id}", headers=hr_headers)
    assert res_get_emp.status_code == 200
    emp_dict = res_get_emp.json()
    assert "pan" not in emp_dict
    assert "pan_number" not in emp_dict

    # 4. Audit details for entry writes contain NO address or contact text
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)
    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.company_id == cid, AuditLog.entity_id == staff_emp.id)
        .all()
    )
    for row in audit_rows:
        if row.details:
            details_str = str(row.details)
            assert "123 Main St" not in details_str
            assert "Bengaluru" not in details_str
            assert "Jane Doe" not in details_str
            assert "+91-9876543210" not in details_str


# ==============================================================================
# R9: Audit Rows for Section Writes
# ==============================================================================


def test_r09_audit_rows_for_section_writes(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    staff_emp = profile_company["emp_staff"]
    hr_headers = _auth_headers(profile_company["hr_admin"])
    cid = profile_company["company"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    # 1. Create writes EMPLOYEE_ENTRY_CREATED
    res_create = client.post(
        f"/api/v1/employees/{staff_emp.id}/skills",
        headers=hr_headers,
        json={"name": "Rust", "level": "intermediate"},
    )
    assert res_create.status_code == 201
    entry_id = res_create.json()["id"]

    audit_create = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_ENTRY_CREATED",
            AuditLog.entity_id == staff_emp.id,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit_create is not None
    details_create = _get_audit_details(audit_create)
    assert details_create["section"] == "skills"
    assert details_create["entry_id"] == entry_id

    # 2. Update writes EMPLOYEE_ENTRY_UPDATED with changed field names
    res_update = client.put(
        f"/api/v1/employees/{staff_emp.id}/skills/{entry_id}",
        headers=hr_headers,
        json={"level": "expert"},
    )
    assert res_update.status_code == 200

    audit_update = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_ENTRY_UPDATED",
            AuditLog.entity_id == staff_emp.id,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit_update is not None
    details_update = _get_audit_details(audit_update)
    assert details_update["section"] == "skills"
    assert "level" in details_update.get("changed_fields", [])

    # 3. No-op update writes NO audit row
    count_before = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    res_noop = client.put(
        f"/api/v1/employees/{staff_emp.id}/skills/{entry_id}",
        headers=hr_headers,
        json={"level": "expert"},
    )
    assert res_noop.status_code == 200
    assert db.query(AuditLog).filter(AuditLog.company_id == cid).count() == count_before

    # 4. Verify writes EMPLOYEE_ENTRY_VERIFIED
    # Create an education entry first
    r_edu = client.post(
        f"/api/v1/employees/{staff_emp.id}/education",
        headers=hr_headers,
        json=VALID_SAMPLES["education"],
    )
    assert r_edu.status_code == 201
    edu_id = r_edu.json()["id"]

    client.post(
        f"/api/v1/employees/{staff_emp.id}/education/{edu_id}/verify",
        headers=hr_headers,
    )
    audit_verify = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_ENTRY_VERIFIED",
            AuditLog.entity_id == staff_emp.id,
        )
        .first()
    )
    assert audit_verify is not None
    assert _get_audit_details(audit_verify)["entry_id"] == edu_id

    # 5. Delete writes EMPLOYEE_ENTRY_DELETED
    res_del = client.delete(
        f"/api/v1/employees/{staff_emp.id}/skills/{entry_id}",
        headers=hr_headers,
    )
    assert res_del.status_code == 204
    audit_del = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_ENTRY_DELETED",
            AuditLog.entity_id == staff_emp.id,
        )
        .first()
    )
    assert audit_del is not None
    assert _get_audit_details(audit_del)["entry_id"] == entry_id


# ==============================================================================
# R10 & Addendum A1, A2, A3: Cross-Company Isolation, Real Co B, RLS & Rate Limit
# ==============================================================================


def test_r10_a1_cross_company_real_isolation(
    client: TestClient, profile_company: dict[str, Any], db: Session
) -> None:
    """A1. R10: create a REAL second company with one employee and one entry per section.
    Using HR of company A, GET, POST, PUT, DELETE, verify and unverify on B's employee id
    and B's entry ids must all give 404, and B's data must be unchanged afterwards.
    """
    from tests.conftest import _make_tenant

    hr_a_headers = _auth_headers(profile_company["hr_admin"])

    # Create real Company B
    code_b = f"CB{uuid.uuid4().hex[:4].upper()}"
    tenant_b = _make_tenant(db, name="Company B", code=code_b)
    cid_b = tenant_b.company_id
    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)

    emp_b = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_code=f"{code_b}-0001",
        first_name="Bob",
        last_name="Builder",
        email=f"bob-{uuid.uuid4().hex[:6]}@companyb.com",
        hire_date=date(2024, 1, 1),
    )
    db.add(emp_b)
    db.flush()

    from app.modules.hr import models as hr_models

    EmployeeAddress = getattr(hr_models, "EmployeeAddress", None)
    EmployeeEmergencyContact = getattr(hr_models, "EmployeeEmergencyContact", None)
    EmployeeSkill = getattr(hr_models, "EmployeeSkill", None)
    EmployeeEducation = getattr(hr_models, "EmployeeEducation", None)
    EmployeeExperience = getattr(hr_models, "EmployeeExperience", None)

    if not all(
        [
            EmployeeAddress,
            EmployeeEmergencyContact,
            EmployeeSkill,
            EmployeeEducation,
            EmployeeExperience,
        ]
    ):
        pytest.fail("HR section models not implemented yet")

    addr_b = EmployeeAddress(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_id=emp_b.id,
        kind="current",
        line1="Company B HQ Street",
        city="Mumbai",
        country="India",
    )
    emg_b = EmployeeEmergencyContact(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_id=emp_b.id,
        name="Mary Builder",
        relationship="Sister",
        phone="+91-1122334455",
    )
    skill_b = EmployeeSkill(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_id=emp_b.id,
        name="Kubernetes",
        level="expert",
    )
    edu_b = EmployeeEducation(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_id=emp_b.id,
        institution="IIT Bombay",
        degree="B.Tech",
        start_date=date(2016, 8, 1),
        verification_status="unverified",
    )
    exp_b = EmployeeExperience(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_id=emp_b.id,
        employer="Startup B",
        job_title="DevOps Lead",
        start_date=date(2020, 1, 1),
        verification_status="unverified",
    )
    db.add_all([addr_b, emg_b, skill_b, edu_b, exp_b])
    db.commit()

    emp_b_id = emp_b.id
    addr_b_id = addr_b.id
    emg_b_id = emg_b.id
    skill_b_id = skill_b.id
    edu_b_id = edu_b.id
    exp_b_id = exp_b.id

    b_entry_map = {
        "addresses": addr_b_id,
        "emergency-contacts": emg_b_id,
        "skills": skill_b_id,
        "education": edu_b_id,
        "experience": exp_b_id,
    }

    # Now with HR of Company A, attempt access to Company B's records
    bind_tenant_to_session(db, company_id=profile_company["company"].id, is_platform_admin=True)

    staff_a = profile_company["emp_staff"]
    for sec in SECTIONS:
        b_entry_id = b_entry_map[sec]
        # GET on B's employee
        assert (
            client.get(f"/api/v1/employees/{emp_b_id}/{sec}", headers=hr_a_headers).status_code
            == 404
        )
        # POST on B's employee
        assert (
            client.post(
                f"/api/v1/employees/{emp_b_id}/{sec}", headers=hr_a_headers, json=VALID_SAMPLES[sec]
            ).status_code
            == 404
        )
        # PUT on B's entry (both using B's employee and A's employee)
        assert (
            client.put(
                f"/api/v1/employees/{emp_b_id}/{sec}/{b_entry_id}",
                headers=hr_a_headers,
                json=VALID_SAMPLES[sec],
            ).status_code
            == 404
        )
        assert (
            client.put(
                f"/api/v1/employees/{staff_a.id}/{sec}/{b_entry_id}",
                headers=hr_a_headers,
                json=VALID_SAMPLES[sec],
            ).status_code
            == 404
        )
        # DELETE on B's entry (both using B's employee and A's employee)
        assert (
            client.delete(
                f"/api/v1/employees/{emp_b_id}/{sec}/{b_entry_id}", headers=hr_a_headers
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v1/employees/{staff_a.id}/{sec}/{b_entry_id}", headers=hr_a_headers
            ).status_code
            == 404
        )

    # Direct query test: Under is_platform_admin=True session, filtering by Company A returns None
    from app.modules.hr.repository import EmployeeSectionRepository

    sec_repo = EmployeeSectionRepository(db)
    # When company_id filter is company A, lookup of company B's entry returns None
    found_entry = sec_repo.get_entry(
        "skills", emp_b_id, skill_b_id, company_id=profile_company["company"].id
    )
    assert found_entry is None, (
        f"Cross-tenant leak: found {found_entry} of Company B when querying Company A!"
    )

    # Verify and unverify on B's edu and exp
    for sec, b_id in [("education", edu_b_id), ("experience", exp_b_id)]:
        assert (
            client.post(
                f"/api/v1/employees/{emp_b_id}/{sec}/{b_id}/verify", headers=hr_a_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/employees/{emp_b_id}/{sec}/{b_id}/unverify", headers=hr_a_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/employees/{staff_a.id}/{sec}/{b_id}/verify", headers=hr_a_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/employees/{staff_a.id}/{sec}/{b_id}/unverify", headers=hr_a_headers
            ).status_code
            == 404
        )

    # Assert Company B's data is unchanged
    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)
    db.expire_all()
    check_addr = db.get(EmployeeAddress, addr_b.id)
    check_emg = db.get(EmployeeEmergencyContact, emg_b.id)
    check_skill = db.get(EmployeeSkill, skill_b.id)
    check_edu = db.get(EmployeeEducation, edu_b.id)
    check_exp = db.get(EmployeeExperience, exp_b.id)
    assert check_addr is not None and check_addr.line1 == "Company B HQ Street"
    assert check_emg is not None and check_emg.name == "Mary Builder"
    assert check_skill is not None and check_skill.name == "Kubernetes"
    assert check_edu is not None and check_edu.verification_status == "unverified"
    assert check_exp is not None and check_exp.verification_status == "unverified"


def test_r10_a2_rls_bound_session_sees_zero_rows_of_other_company(
    db: Session, profile_company: dict[str, Any]
) -> None:
    """A2. R10: for each of the 5 new tables, a test with a session bound to company A
    (not platform admin) must see 0 rows of company B.
    """
    from tests.conftest import _make_tenant

    cid_a = profile_company["company"].id

    # Create Company B and seed entries in the 5 tables
    code_b = f"RLS{uuid.uuid4().hex[:4].upper()}"
    tenant_b = _make_tenant(db, name="Company B RLS", code=code_b)
    cid_b = tenant_b.company_id
    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)

    emp_b = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_code=f"{code_b}-0001",
        first_name="RLSBob",
        email=f"rlsbob-{uuid.uuid4().hex[:6]}@companyb.com",
        hire_date=date(2024, 1, 1),
    )
    db.add(emp_b)
    db.flush()

    from app.modules.hr import models as hr_models

    EmployeeAddress = getattr(hr_models, "EmployeeAddress", None)
    EmployeeEmergencyContact = getattr(hr_models, "EmployeeEmergencyContact", None)
    EmployeeSkill = getattr(hr_models, "EmployeeSkill", None)
    EmployeeEducation = getattr(hr_models, "EmployeeEducation", None)
    EmployeeExperience = getattr(hr_models, "EmployeeExperience", None)

    if not all(
        [
            EmployeeAddress,
            EmployeeEmergencyContact,
            EmployeeSkill,
            EmployeeEducation,
            EmployeeExperience,
        ]
    ):
        pytest.fail("HR section models not implemented yet")

    db.add_all(
        [
            EmployeeAddress(
                id=uuid.uuid4(),
                company_id=cid_b,
                employee_id=emp_b.id,
                kind="current",
                line1="B Line 1",
                city="Mumbai",
                country="India",
            ),
            EmployeeEmergencyContact(
                id=uuid.uuid4(),
                company_id=cid_b,
                employee_id=emp_b.id,
                name="B Contact",
                relationship="Friend",
                phone="+1111111111",
            ),
            EmployeeSkill(
                id=uuid.uuid4(),
                company_id=cid_b,
                employee_id=emp_b.id,
                name="BSkill",
                level="beginner",
            ),
            EmployeeEducation(
                id=uuid.uuid4(),
                company_id=cid_b,
                employee_id=emp_b.id,
                institution="B School",
                degree="BSc",
                start_date=date(2020, 1, 1),
            ),
            EmployeeExperience(
                id=uuid.uuid4(),
                company_id=cid_b,
                employee_id=emp_b.id,
                employer="B Corp",
                job_title="Engineer",
                start_date=date(2021, 1, 1),
            ),
        ]
    )
    db.commit()

    # Now bind session to Company A with is_platform_admin=False
    bind_tenant_to_session(db, company_id=cid_a, is_platform_admin=False)

    tables = [
        "employee_addresses",
        "employee_emergency_contacts",
        "employee_skills",
        "employee_education",
        "employee_experience",
    ]
    for tbl in tables:
        # Direct SQL query under RLS should see 0 rows belonging to Company B
        count_b_rows = db.execute(
            text(f"SELECT count(*) FROM {tbl} WHERE company_id = :cid_b"),
            {"cid_b": cid_b},
        ).scalar()
        assert count_b_rows == 0, (
            f"RLS violation: Company A session can see {count_b_rows} rows in {tbl} of Company B!"
        )


RATE_LIMIT_CASES = [
    ("post", "/api/v1/employees/{emp_id}/skills", "POST"),
    ("put", "/api/v1/employees/{emp_id}/skills/{entry_id}", "PUT"),
    ("delete", "/api/v1/employees/{emp_id}/skills/{entry_id}", "DELETE"),
    ("verify", "/api/v1/employees/{emp_id}/education/{entry_id}/verify", "POST"),
    ("unverify", "/api/v1/employees/{emp_id}/education/{entry_id}/unverify", "POST"),
]


@pytest.mark.parametrize("route_type,path_template,method", RATE_LIMIT_CASES)
def test_r10_a3_rate_limiting_exact_30_per_min(
    client: TestClient,
    profile_company: dict[str, Any],
    route_type: str,
    path_template: str,
    method: str,
) -> None:
    """A3. R10: parametrize rate-limit test over every write route
    (POST, PUT, DELETE, verify, unverify): 31st call gives 429. Exact expectations.
    """
    staff_emp = profile_company["emp_staff"]
    hr_headers = _auth_headers(profile_company["hr_admin"])

    # Prepare prerequisites if route needs an existing entry_id
    entry_id = None
    if "{entry_id}" in path_template:
        sec = "education" if "education" in path_template else "skills"
        r = client.post(
            f"/api/v1/employees/{staff_emp.id}/{sec}",
            headers=hr_headers,
            json=VALID_SAMPLES[sec],
        )
        assert r.status_code == 201
        entry_id = r.json()["id"]

    url = path_template.format(emp_id=staff_emp.id, entry_id=entry_id)

    limiter.enabled = True
    try:
        limiter.reset()
        status_codes: list[int] = []
        for i in range(35):
            if method == "POST":
                payload = (
                    {"name": f"SkillR-{i}", "level": "intermediate"}
                    if route_type == "post"
                    else None
                )
                res = client.post(url, headers=hr_headers, json=payload)
            elif method == "PUT":
                res = client.put(url, headers=hr_headers, json={"level": "expert"})
            elif method == "DELETE":
                res = client.delete(url, headers=hr_headers)
            status_codes.append(res.status_code)

        # First 30 calls must not be 429
        assert all(c != 429 for c in status_codes[:30]), (
            f"[{route_type}] Expected first 30 calls not 429, got: {status_codes[:30]}"
        )
        # Calls 31 to 35 must all be 429
        assert all(c == 429 for c in status_codes[30:]), (
            f"[{route_type}] Expected calls 31-35 to be 429, got: {status_codes[30:]}"
        )
    finally:
        limiter.reset()
        limiter.enabled = False
