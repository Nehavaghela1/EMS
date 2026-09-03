import pytest
from fastapi.testclient import TestClient

from tests.conftest import TenantContext


def test_statutory_configs_are_tenant_isolated(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    # Company A updates its statutory config (pf_wage_ceiling = 18000)
    res_a_update = client.put(
        "/api/v1/payroll/statutory-config",
        json={"pf_wage_ceiling": "18000.00"},
        headers=company_a.hr_headers,
    )
    assert res_a_update.status_code == 200
    assert res_a_update.json()["pf_wage_ceiling"] == "18000.00"

    # Company B gets its statutory config - must see its own defaults (15000), not Company A's 18000
    res_b_get = client.get("/api/v1/payroll/statutory-config", headers=company_b.hr_headers)
    assert res_b_get.status_code == 200
    assert res_b_get.json()["pf_wage_ceiling"] == "15000.00"
