"""Matches Spec 8.6's canonical isolation-suite shape (companies/
departments/employees before it). `test_rls_policies.py`'s parametrized
sweep already covers `leaves`, `leave_types`, `leave_balances` and
`holidays` automatically, with no edits to that file — this is the
additional HTTP-level, data-shaped proof for the leave application flow.
"""


def test_leaves_are_tenant_isolated(client, company_a, company_b):
    leave_type = client.post(
        "/api/v1/leave-types",
        headers=company_a.hr_headers,
        json={"name": "Annual Leave", "code": "annual", "annual_allowance": "20"},
    ).json()
    employee = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={
            "first_name": "Isolated",
            "email": "isolated@leaveiso.com",
            "hire_date": "2024-01-01",
        },
    ).json()

    created = client.post(
        "/api/v1/leaves",
        headers=company_a.hr_headers,
        json={
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "start_date": "2031-03-03",
            "end_date": "2031-03-03",
            "is_half_day": True,
            "reason": "Isolation check",
        },
    )
    assert created.status_code == 201, created.text
    leave_id = created.json()["id"]

    # Act: authenticate as company B and try every way in.
    assert client.get("/api/v1/leaves", headers=company_b.hr_headers).json()["items"] == []
    assert client.get(f"/api/v1/leaves/{leave_id}", headers=company_b.hr_headers).status_code == 404
    assert (
        client.put(
            f"/api/v1/leaves/{leave_id}", headers=company_b.hr_headers, json={"status": "approved"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/leaves/{leave_id}", headers=company_b.hr_headers).status_code == 404
    )
    assert client.get("/api/v1/leave-types", headers=company_b.hr_headers).json() == []

    # Company A itself still sees it correctly — this isn't a general
    # outage, it's tenant isolation specifically.
    own = client.get(f"/api/v1/leaves/{leave_id}", headers=company_a.hr_headers)
    assert own.status_code == 200
