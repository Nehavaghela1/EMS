"""Matches Spec 8.6's canonical isolation-suite shape almost verbatim
(its own worked example uses `/employees`; departments is the first real
tenant-scoped CRUD resource that exists to run it against).
"""


def test_departments_are_tenant_isolated(client, company_a, company_b):
    created = client.post(
        "/api/v1/departments", headers=company_a.hr_headers, json={"name": "Engineering"}
    )
    assert created.status_code == 201
    department_id = created.json()["id"]

    # Act: authenticate as company B and try every way in.
    assert client.get("/api/v1/departments", headers=company_b.hr_headers).json()["items"] == []
    assert (
        client.get(f"/api/v1/departments/{department_id}", headers=company_b.hr_headers).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/departments/{department_id}",
            headers=company_b.hr_headers,
            json={"name": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/departments/{department_id}", headers=company_b.hr_headers
        ).status_code
        == 404
    )

    # Company A itself still sees it correctly — this isn't a general outage,
    # it's tenant isolation specifically.
    own = client.get(f"/api/v1/departments/{department_id}", headers=company_a.hr_headers)
    assert own.status_code == 200
    assert own.json()["name"] == "Engineering"
