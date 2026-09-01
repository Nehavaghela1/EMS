"""WP-11 routes 125-127: in-app notifications, emitted on leave approved,
leave rejected, and attendance regularization (Spec 7.8, 10.8). List,
mark-one-read, mark-all-read, unread count.
"""

import uuid

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@notifco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@notifco.com",
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


def _create_leave_type(client, headers, **overrides) -> dict:
    payload = {
        "name": "Annual Leave",
        "code": f"annual-{uuid.uuid4().hex[:6]}",
        "annual_allowance": "20",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/leave-types", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_leave_approval_and_rejection_each_notify_the_employee(client, company_a, db):
    leave_type = _create_leave_type(client, company_a.hr_headers)
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    approved = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": "2031-05-05",
            "end_date": "2031-05-05",
            "is_half_day": True,
            "reason": "Notify check",
        },
    ).json()
    client.put(
        f"/api/v1/leaves/{approved['id']}",
        headers=company_a.hr_headers,
        json={"status": "approved"},
    )

    rejected = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": "2031-05-06",
            "end_date": "2031-05-06",
            "is_half_day": True,
            "reason": "Notify check 2",
        },
    ).json()
    client.put(
        f"/api/v1/leaves/{rejected['id']}",
        headers=company_a.hr_headers,
        json={"status": "rejected", "rejection_reason": "No cover available"},
    )

    listed = client.get("/api/v1/notifications", headers=own_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    types = {row["type"] for row in body["items"]}
    assert {"leave_approved", "leave_rejected"} <= types
    assert body["unread_count"] >= 2


def test_attendance_regularization_notifies_the_employee(client, company_a, db):
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    created = client.post("/api/v1/attendance/check-in", headers=own_headers).json()
    client.put(
        f"/api/v1/attendance/{created['id']}",
        headers=company_a.hr_headers,
        json={"status": "wfh", "reason": "Forgot to mark WFH"},
    )

    listed = client.get("/api/v1/notifications", headers=own_headers)
    assert listed.status_code == 200
    types = {row["type"] for row in listed.json()["items"]}
    assert "attendance_regularized" in types


def test_mark_one_read_and_mark_all_read_and_unread_count(client, company_a, db):
    leave_type = _create_leave_type(client, company_a.hr_headers)
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )

    for i in range(2):
        leave = client.post(
            "/api/v1/leaves",
            headers=company_a.hr_headers,
            json={
                "employee_id": employee["id"],
                "leave_type_id": leave_type["id"],
                "start_date": f"2031-06-{10 + i:02d}",
                "end_date": f"2031-06-{10 + i:02d}",
                "is_half_day": True,
                "reason": f"Mark read check {i}",
            },
        ).json()
        client.put(
            f"/api/v1/leaves/{leave['id']}",
            headers=company_a.hr_headers,
            json={"status": "approved"},
        )

    listed = client.get("/api/v1/notifications", headers=own_headers)
    assert listed.json()["unread_count"] == 2
    first_id = listed.json()["items"][0]["id"]

    mark_one = client.put(f"/api/v1/notifications/{first_id}/read", headers=own_headers)
    assert mark_one.status_code == 200, mark_one.text
    assert mark_one.json()["is_read"] is True
    assert mark_one.json()["read_at"] is not None

    after_one = client.get("/api/v1/notifications", headers=own_headers)
    assert after_one.json()["unread_count"] == 1

    mark_all = client.put("/api/v1/notifications/read-all", headers=own_headers)
    assert mark_all.status_code == 200
    assert mark_all.json()["marked_read"] == 1

    after_all = client.get("/api/v1/notifications", headers=own_headers)
    assert after_all.json()["unread_count"] == 0

    unread_only = client.get("/api/v1/notifications?unread_only=true", headers=own_headers)
    assert unread_only.json()["items"] == []


def test_a_notification_belonging_to_another_user_404s_not_403s(client, company_a, db):
    """10.1's 404-not-403 rule extends to notifications: reading someone
    else's notification id must look like it doesn't exist, not like a
    permission wall."""
    leave_type = _create_leave_type(client, company_a.hr_headers)
    employee = _create_employee(client, company_a.hr_headers)
    own_headers = _link_user_to_employee(
        db, company_a.company_id, employee["id"], UserRole.employee
    )
    leave = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": "2031-07-01",
            "end_date": "2031-07-01",
            "is_half_day": True,
            "reason": "404 check",
        },
    ).json()
    client.put(
        f"/api/v1/leaves/{leave['id']}", headers=company_a.hr_headers, json={"status": "approved"}
    )
    notification_id = client.get("/api/v1/notifications", headers=own_headers).json()["items"][0][
        "id"
    ]

    other = client.put(
        f"/api/v1/notifications/{notification_id}/read", headers=company_a.hr_headers
    )
    assert other.status_code == 404
