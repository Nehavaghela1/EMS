"""WP-09: shift CRUD, delete blocked while currently assigned, and
rejecting a second overlapping assignment for the same employee.
"""

import uuid

from app.core.time import utcnow


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@shiftco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_shift(client, headers, **overrides) -> dict:
    payload = {"name": "Day Shift", "start_time": "09:00:00", "end_time": "18:00:00"}
    payload.update(overrides)
    resp = client.post("/api/v1/shifts", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_shift_crud(client, company_a):
    created = _create_shift(client, company_a.hr_headers, name="Morning")
    assert created["break_minutes"] == 60

    listed = client.get("/api/v1/shifts", headers=company_a.hr_headers)
    assert listed.status_code == 200
    assert created["id"] in {s["id"] for s in listed.json()["items"]}

    updated = client.put(
        f"/api/v1/shifts/{created['id']}",
        headers=company_a.hr_headers,
        json={"break_minutes": 45},
    )
    assert updated.status_code == 200
    assert updated.json()["break_minutes"] == 45

    deleted = client.delete(f"/api/v1/shifts/{created['id']}", headers=company_a.hr_headers)
    assert deleted.status_code == 204


def test_delete_blocked_while_currently_assigned(client, company_a):
    shift = _create_shift(client, company_a.hr_headers, name="Assigned Shift")
    employee = _create_employee(client, company_a.hr_headers)
    today = utcnow().date()

    assign_resp = client.post(
        f"/api/v1/shifts/{shift['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": employee["id"], "effective_from": today.isoformat()},
    )
    assert assign_resp.status_code == 201

    blocked = client.delete(f"/api/v1/shifts/{shift['id']}", headers=company_a.hr_headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["details"]["assignment_count"] == 1


def test_a_second_overlapping_assignment_is_rejected(client, company_a):
    shift_a = _create_shift(client, company_a.hr_headers, name="Shift A")
    shift_b = _create_shift(client, company_a.hr_headers, name="Shift B")
    employee = _create_employee(client, company_a.hr_headers)
    today = utcnow().date()

    first = client.post(
        f"/api/v1/shifts/{shift_a['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": employee["id"], "effective_from": today.isoformat()},
    )
    assert first.status_code == 201

    # Open-ended (no effective_to) assignment already covers today onward —
    # any new assignment starting on or after today overlaps it.
    second = client.post(
        f"/api/v1/shifts/{shift_b['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": employee["id"], "effective_from": today.isoformat()},
    )
    assert second.status_code == 409

    # A non-overlapping assignment for a DIFFERENT employee succeeds.
    other_employee = _create_employee(client, company_a.hr_headers, email="other@shiftco.com")
    third = client.post(
        f"/api/v1/shifts/{shift_b['id']}/assign",
        headers=company_a.hr_headers,
        json={"employee_id": other_employee["id"], "effective_from": today.isoformat()},
    )
    assert third.status_code == 201
