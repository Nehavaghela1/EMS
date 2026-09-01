"""WP-11 route 121 (Spec 11.10): all four role shapes, and the Redis cache
— a second call within the TTL must be served from cache, not hit the
repository again.
"""

import uuid

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from app.modules.platform.repository import DashboardRepository


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@dashco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@dashco.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    employee.user_id = user.id
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


def test_hr_admin_dashboard_shape(client, company_a):
    _create_employee(client, company_a.hr_headers)
    resp = client.get("/api/v1/dashboard", headers=company_a.hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "hr_admin"
    data = body["data"]
    assert data["headcount"] >= 1
    for field in (
        "present_today",
        "on_leave_today",
        "pending_leave_requests",
        "pending_reimbursements",
        "recent_hires",
        "department_distribution",
        "last_payroll_run",
    ):
        assert field in data


def test_manager_dashboard_shape(client, company_a):
    resp = client.get("/api/v1/dashboard", headers=company_a.manager_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "manager"
    data = body["data"]
    # The manager fixture has no linked employee record — team stats are
    # correctly all zero, not an error.
    assert data["team_headcount"] == 0
    assert data["team_present_today"] == 0
    assert data["team_leave_requests_awaiting"] == 0
    assert "team_task_load" in data


def test_employee_dashboard_shape_with_real_data(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    client.post("/api/v1/attendance/check-in", headers=own_headers)

    resp = client.get("/api/v1/dashboard", headers=own_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "employee"
    data = body["data"]
    assert data["attendance_this_month"].get("present") == 1
    assert "leave_balances" in data
    assert "pending_requests" in data


def test_super_admin_dashboard_shape(client, super_admin_headers):
    resp = client.get("/api/v1/dashboard", headers=super_admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "super_admin"
    data = body["data"]
    assert "company_counts_by_status" in data
    assert "pending_approvals" in data
    assert data["platform_user_count"] >= 1


def test_dashboard_is_served_from_cache_on_a_second_call_within_the_ttl(
    client, company_a, monkeypatch
):
    _create_employee(client, company_a.hr_headers)

    call_count = 0
    original = DashboardRepository.headcount

    def _counting_headcount(self, company_id):
        nonlocal call_count
        call_count += 1
        return original(self, company_id)

    monkeypatch.setattr(DashboardRepository, "headcount", _counting_headcount)

    first = client.get("/api/v1/dashboard", headers=company_a.hr_headers)
    assert first.status_code == 200
    second = client.get("/api/v1/dashboard", headers=company_a.hr_headers)
    assert second.status_code == 200
    assert first.json()["data"]["headcount"] == second.json()["data"]["headcount"]

    assert call_count == 1, "the second call within the TTL must be served from cache"
