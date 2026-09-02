"""WP-07: employee CRUD, search/filter/sort/pagination via the shared
helper (10.1), concurrency-safe employee_code generation (11.2), soft
deactivate, manager scoping, and the two WP-06 gaps this package closes
(live department employee counts, 409-blocked delete).
"""

import uuid

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@companya.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    """No `/auth/activate` route exists yet (WP-03 was skipped this
    session) — tests that need a role-specific caller linked to a real
    employee row link it directly, the same way conftest already builds
    role-specific users."""
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@companya.com",
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


def test_create_employee_generates_sequential_codes_and_sends_an_invitation(
    client, company_a, email_outbox
):
    first = _create_employee(client, company_a.hr_headers, first_name="Alice")
    second = _create_employee(client, company_a.hr_headers, first_name="Bob")

    assert first["employee_code"].endswith("-0001")
    assert second["employee_code"].endswith("-0002")
    assert first["employee_code"].split("-0001")[0] == second["employee_code"].split("-0002")[0]
    # No raw token in the response (CLAUDE.md rule 10) — just where it went.
    assert first["invite"]["sent_to"] == first["email"]
    assert first["invite"]["expires_at"]
    assert first["invitation_status"] == "sent"

    sent = [e for e in email_outbox if e["to"] == first["email"] and "invited" in e["subject"]]
    assert sent, email_outbox
    assert "/activate/" in sent[-1]["text_body"]
    assert first["is_active"] is True
    assert first["user_id"] is None


def test_duplicate_email_in_the_same_company_is_rejected(client, company_a):
    _create_employee(client, company_a.hr_headers, email="dup@companya.com")
    resp = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={"first_name": "Dup", "email": "dup@companya.com", "hire_date": "2024-01-01"},
    )
    assert resp.status_code == 409


def test_invalid_department_reference_is_rejected(client, company_a):
    resp = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={
            "first_name": "Nowhere",
            "email": "nowhere@companya.com",
            "hire_date": "2024-01-01",
            "department_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_reference"


def test_list_supports_q_department_filter_sort_and_pagination(client, company_a):
    dept = client.post(
        "/api/v1/departments", headers=company_a.hr_headers, json={"name": "Engineering"}
    ).json()

    _create_employee(
        client,
        company_a.hr_headers,
        first_name="Amy",
        last_name="Adams",
        email="amy@companya.com",
        hire_date="2024-03-01",
        department_id=dept["id"],
    )
    _create_employee(
        client,
        company_a.hr_headers,
        first_name="Ben",
        last_name="Brown",
        email="ben@companya.com",
        hire_date="2024-01-01",
    )
    _create_employee(
        client,
        company_a.hr_headers,
        first_name="Cara",
        last_name="Clark",
        email="cara@companya.com",
        hire_date="2024-02-01",
    )

    # q matches first_name, last_name, email, employee_code — case-insensitive.
    q_resp = client.get("/api/v1/employees?q=amy", headers=company_a.hr_headers)
    assert q_resp.status_code == 200
    assert [e["first_name"] for e in q_resp.json()["items"]] == ["Amy"]

    # department_id filter.
    dept_resp = client.get(
        f"/api/v1/employees?department_id={dept['id']}", headers=company_a.hr_headers
    )
    assert [e["first_name"] for e in dept_resp.json()["items"]] == ["Amy"]

    # sort=-hire_date.
    sort_resp = client.get("/api/v1/employees?sort=-hire_date", headers=company_a.hr_headers)
    names = [e["first_name"] for e in sort_resp.json()["items"]]
    assert names == ["Amy", "Cara", "Ben"]

    # page=2&limit=... and the exact 10.1 envelope.
    page_resp = client.get("/api/v1/employees?page=2&limit=2", headers=company_a.hr_headers)
    body = page_resp.json()
    assert set(body.keys()) == {"items", "page", "limit", "total", "pages", "has_next"}
    assert body["page"] == 2
    assert body["limit"] == 2
    assert body["total"] == 3
    assert body["pages"] == 2
    assert body["has_next"] is False
    assert len(body["items"]) == 1


def test_invalid_sort_column_returns_400_not_an_interpolated_order_by(client, company_a):
    resp = client.get("/api/v1/employees?sort=hashed_password", headers=company_a.hr_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_sort"


def test_manager_sees_only_their_own_direct_reports(client, company_a, db):
    manager_employee = _create_employee(
        client, company_a.hr_headers, first_name="Mia", email="mia@companya.com"
    )
    manager_headers = _link_user_to_employee(
        db, company_a.company_id, manager_employee["id"], UserRole.manager
    )

    report_a = _create_employee(
        client,
        company_a.hr_headers,
        first_name="Report1",
        email="report1@companya.com",
        reporting_manager_id=manager_employee["id"],
    )
    report_b = _create_employee(
        client,
        company_a.hr_headers,
        first_name="Report2",
        email="report2@companya.com",
        reporting_manager_id=manager_employee["id"],
    )
    _create_employee(
        client, company_a.hr_headers, first_name="NotMyReport", email="other@companya.com"
    )

    resp = client.get("/api/v1/employees", headers=manager_headers)
    assert resp.status_code == 200
    ids = {e["id"] for e in resp.json()["items"]}
    assert ids == {report_a["id"], report_b["id"]}

    # The manager cannot use the filter to escape their own scope either.
    escape_resp = client.get(
        f"/api/v1/employees?reporting_manager_id={manager_employee['id']}", headers=manager_headers
    )
    escape_ids = {e["id"] for e in escape_resp.json()["items"]}
    assert escape_ids == {report_a["id"], report_b["id"]}


def test_own_employee_may_only_update_contact_fields(client, company_a, db):
    employee = _create_employee(
        client, company_a.hr_headers, first_name="Owen", email="owen@companya.com"
    )
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    contact_resp = client.put(
        f"/api/v1/employees/{employee['id']}",
        headers=own_headers,
        json={"phone": "+91-9999999999"},
    )
    assert contact_resp.status_code == 200
    assert contact_resp.json()["phone"] == "+91-9999999999"

    restricted_resp = client.put(
        f"/api/v1/employees/{employee['id']}",
        headers=own_headers,
        json={"position": "Senior Engineer"},
    )
    assert restricted_resp.status_code == 403


def test_hr_can_update_hr_only_fields(client, company_a):
    employee = _create_employee(
        client, company_a.hr_headers, first_name="Hank", email="hank@companya.com"
    )
    resp = client.put(
        f"/api/v1/employees/{employee['id']}",
        headers=company_a.hr_headers,
        json={"position": "Staff Engineer", "level": "L4"},
    )
    assert resp.status_code == 200
    assert resp.json()["position"] == "Staff Engineer"
    assert resp.json()["level"] == "L4"


def test_deactivated_employee_row_still_exists_and_stays_visible_by_id(client, company_a, db):
    """Hardening pass: GET-by-id used to 404 a deactivated employee (it
    filtered on is_active, same as the list's default view), which made the
    frontend's own "Reactivate" button on that exact page unreachable — HR
    could never load the page it lived on. is_active=False is now a visible
    field on the response instead of a 404 (6.5: the row is soft-deactivated,
    never hard-deleted, so hiding it from a direct id lookup was never
    required for isolation — company_id, not is_active, is the tenant
    boundary)."""
    employee = _create_employee(
        client, company_a.hr_headers, first_name="Diana", email="diana@companya.com"
    )
    employee_id = employee["id"]

    delete_resp = client.delete(f"/api/v1/employees/{employee_id}", headers=company_a.hr_headers)
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/v1/employees/{employee_id}", headers=company_a.hr_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["is_active"] is False

    row = db.get(Employee, uuid.UUID(employee_id))
    assert row is not None
    assert row.is_active is False
    assert row.deleted_at is None  # never a hard delete (6.5)


def test_toggle_active_reactivates_a_deactivated_employee(client, company_a):
    employee = _create_employee(
        client, company_a.hr_headers, first_name="Rae", email="rae@companya.com"
    )
    employee_id = employee["id"]
    client.delete(f"/api/v1/employees/{employee_id}", headers=company_a.hr_headers)
    deactivated_get = client.get(f"/api/v1/employees/{employee_id}", headers=company_a.hr_headers)
    assert deactivated_get.status_code == 200
    assert deactivated_get.json()["is_active"] is False

    reactivate_resp = client.post(
        f"/api/v1/employees/{employee_id}/toggle-active", headers=company_a.hr_headers
    )
    assert reactivate_resp.status_code == 200
    assert reactivate_resp.json()["is_active"] is True

    get_resp = client.get(f"/api/v1/employees/{employee_id}", headers=company_a.hr_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["is_active"] is True


def test_deactivating_an_employee_also_deactivates_their_linked_user(client, company_a, db):
    employee = _create_employee(
        client, company_a.hr_headers, first_name="Uma", email="uma@companya.com"
    )
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    assert client.get("/api/v1/employees/me", headers=own_headers).status_code == 200

    client.delete(f"/api/v1/employees/{employee['id']}", headers=company_a.hr_headers)

    # The linked user is now inactive — get_current_user rejects it (9.2).
    assert client.get("/api/v1/employees/me", headers=own_headers).status_code == 401


def test_department_list_reports_live_employee_counts(client, company_a):
    dept = client.post(
        "/api/v1/departments", headers=company_a.hr_headers, json={"name": "Design"}
    ).json()
    assert dept["employee_count"] == 0

    _create_employee(
        client, company_a.hr_headers, email="d1@companya.com", department_id=dept["id"]
    )
    _create_employee(
        client, company_a.hr_headers, email="d2@companya.com", department_id=dept["id"]
    )

    list_resp = client.get("/api/v1/departments", headers=company_a.hr_headers)
    listed = next(d for d in list_resp.json()["items"] if d["id"] == dept["id"])
    assert listed["employee_count"] == 2

    detail_resp = client.get(f"/api/v1/departments/{dept['id']}", headers=company_a.hr_headers)
    assert detail_resp.json()["employee_count"] == 2


def test_deleting_a_department_with_employees_returns_409_with_the_count(client, company_a):
    dept = client.post(
        "/api/v1/departments", headers=company_a.hr_headers, json={"name": "Sales"}
    ).json()
    employee = _create_employee(
        client, company_a.hr_headers, email="s1@companya.com", department_id=dept["id"]
    )

    blocked_resp = client.delete(f"/api/v1/departments/{dept['id']}", headers=company_a.hr_headers)
    assert blocked_resp.status_code == 409
    assert blocked_resp.json()["error"]["details"]["employee_count"] == 1

    # Deactivating the only employee (never a hard delete, 6.5) drops the
    # active count to zero, and the same delete now succeeds.
    client.delete(f"/api/v1/employees/{employee['id']}", headers=company_a.hr_headers)
    ok_resp = client.delete(f"/api/v1/departments/{dept['id']}", headers=company_a.hr_headers)
    assert ok_resp.status_code == 204
