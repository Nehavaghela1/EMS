import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from tests.conftest import TenantContext
from tests.integration.test_employees import _create_employee


def _link_user_to_employee(
    db: Session,
    company_id: uuid.UUID,
    employee_id: str,
    role: UserRole,
    is_active: bool = True,
) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    assert employee is not None
    employee.user_id = user.id
    if not is_active:
        employee.is_active = False
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def test_create_pip_mentor_validation(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """
    Validation of data.mentor_id in create_pip:
    - Cases: mentor in another company (404), mentor not existing (404),
      mentor inactive (409), mentor valid (201), mentor_id omitted (201).
    - Check order: find item (404), authority (403), state (409).
    """
    # 1. Direct Manager
    mgr_emp = _create_employee(
        client, company_a.hr_headers, email=f"mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    mgr_headers = _link_user_to_employee(db, company_a.company_id, mgr_emp["id"], UserRole.manager)

    # 2. Direct Report
    rep_emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"rep-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=mgr_emp["id"],
    )
    _link_user_to_employee(db, company_a.company_id, rep_emp["id"], UserRole.employee)

    # 3. Active Mentor in Company A
    mentor_active = _create_employee(
        client, company_a.hr_headers, email=f"mentor-act-{uuid.uuid4().hex[:6]}@example.com"
    )

    # 4. Inactive Mentor in Company A
    mentor_inactive = _create_employee(
        client, company_a.hr_headers, email=f"mentor-inact-{uuid.uuid4().hex[:6]}@example.com"
    )
    db_mentor_inact = db.get(Employee, uuid.UUID(mentor_inactive["id"]))
    assert db_mentor_inact is not None
    db_mentor_inact.is_active = False
    db.commit()

    # 5. Mentor in Company B
    mentor_b = _create_employee(
        client, company_b.hr_headers, email=f"mentor-b-{uuid.uuid4().hex[:6]}@example.com"
    )

    # Case 1: mentor in another company -> NotFoundError (404)
    res_other_co = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "mentor_id": mentor_b["id"],
            "title": "PIP with Other Company Mentor",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_other_co.status_code == 404, (
        f"Expected 404 for mentor in another company, got {res_other_co.status_code}: "
        f"{res_other_co.text}"
    )

    # Case 2: mentor not existing -> NotFoundError (404)
    non_existent_id = str(uuid.uuid4())
    res_non_existent = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "mentor_id": non_existent_id,
            "title": "PIP with Non-existent Mentor",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_non_existent.status_code == 404, (
        f"Expected 404 for non-existent mentor, got {res_non_existent.status_code}: "
        f"{res_non_existent.text}"
    )

    # Case 3: mentor inactive -> ConflictError (409)
    res_inactive = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "mentor_id": mentor_inactive["id"],
            "title": "PIP with Inactive Mentor",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_inactive.status_code == 409, (
        f"Expected 409 for inactive mentor, got {res_inactive.status_code}: {res_inactive.text}"
    )

    # Case 4: mentor valid -> 201
    res_valid = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp["id"],
            "mentor_id": mentor_active["id"],
            "title": "PIP with Valid Mentor",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_valid.status_code == 201, (
        f"Expected 201 for valid mentor, got {res_valid.status_code}: {res_valid.text}"
    )
    assert res_valid.json()["mentor_id"] == mentor_active["id"]

    # Another report employee to test mentor_id omitted
    rep_emp_2 = _create_employee(
        client,
        company_a.hr_headers,
        email=f"rep2-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=mgr_emp["id"],
    )
    _link_user_to_employee(db, company_a.company_id, rep_emp_2["id"], UserRole.employee)

    # Case 5: mentor_id omitted -> 201
    res_omitted = client.post(
        "/api/v1/performance/pips",
        headers=mgr_headers,
        json={
            "employee_id": rep_emp_2["id"],
            "title": "PIP with Omitted Mentor",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    assert res_omitted.status_code == 201, (
        f"Expected 201 for omitted mentor, got {res_omitted.status_code}: {res_omitted.text}"
    )
    assert res_omitted.json()["mentor_id"] is None
