import uuid
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TenantContext


def test_salary_structures_are_tenant_isolated(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    # Company A creates a salary structure
    res_a = client.post(
        "/api/v1/payroll/structures",
        json={"name": "Company A Software Structure", "components": []},
        headers=company_a.hr_headers,
    )
    assert res_a.status_code == 201
    struct_a_id = res_a.json()["id"]

    # Company B lists structures — must not see Company A's structure
    res_b_list = client.get("/api/v1/payroll/structures", headers=company_b.hr_headers)
    assert res_b_list.status_code == 200
    b_ids = [s["id"] for s in res_b_list.json()["items"]]
    assert struct_a_id not in b_ids

    # Company B tries to get Company A's structure directly — must return 404 (not 403)
    res_b_get = client.get(
        f"/api/v1/payroll/structures/{struct_a_id}", headers=company_b.hr_headers
    )
    assert res_b_get.status_code == 404

    # Company B tries to update Company A's structure — must return 404
    res_b_put = client.put(
        f"/api/v1/payroll/structures/{struct_a_id}",
        json={"name": "Hacked Name"},
        headers=company_b.hr_headers,
    )
    assert res_b_put.status_code == 404

    # Company B tries to delete Company A's structure — must return 404
    res_b_del = client.delete(
        f"/api/v1/payroll/structures/{struct_a_id}", headers=company_b.hr_headers
    )
    assert res_b_del.status_code == 404
