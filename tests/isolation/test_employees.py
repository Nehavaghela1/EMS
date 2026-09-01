"""Matches Spec 8.6's canonical isolation-suite shape (its own worked
example names `/employees` directly — this is the first package where that
literal route exists to run it against). `test_rls_policies.py`'s
parametrized sweep already covers `employees` automatically, with no edits
to that file — this is the additional HTTP-level, data-shaped proof.
"""


def test_employees_are_tenant_isolated(client, company_a, company_b):
    created = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={
            "first_name": "Isolated",
            "email": "isolated@companya.com",
            "hire_date": "2024-01-01",
        },
    )
    assert created.status_code == 201
    employee_id = created.json()["id"]

    # Act: authenticate as company B and try every way in.
    assert client.get("/api/v1/employees", headers=company_b.hr_headers).json()["items"] == []
    assert (
        client.get(f"/api/v1/employees/{employee_id}", headers=company_b.hr_headers).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/employees/{employee_id}",
            headers=company_b.hr_headers,
            json={"phone": "hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/employees/{employee_id}", headers=company_b.hr_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/employees/{employee_id}/toggle-active", headers=company_b.hr_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/employees/{employee_id}/resend-invite", headers=company_b.hr_headers
        ).status_code
        == 404
    )

    # Company A itself still sees it correctly — this isn't a general
    # outage, it's tenant isolation specifically.
    own = client.get(f"/api/v1/employees/{employee_id}", headers=company_a.hr_headers)
    assert own.status_code == 200
    assert own.json()["first_name"] == "Isolated"
