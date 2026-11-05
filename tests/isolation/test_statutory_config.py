from fastapi.testclient import TestClient

from tests.conftest import TenantContext


def test_statutory_configs_are_tenant_isolated(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    # Company A switches PF off and chooses the old regime (5.2: the rates and ceilings are
    # platform rows now, so what a company owns are its switches, state and regime).
    res_a_update = client.put(
        "/api/v1/payroll/statutory-config",
        json={"pf_enabled": False, "default_tax_regime": "old"},
        headers=company_a.hr_headers,
    )
    assert res_a_update.status_code == 200
    assert res_a_update.json()["pf_enabled"] is False

    # Company B gets its statutory config - must see its own defaults, not Company A's choices
    res_b_get = client.get("/api/v1/payroll/statutory-config", headers=company_b.hr_headers)
    assert res_b_get.status_code == 200
    assert res_b_get.json()["pf_enabled"] is True
    assert res_b_get.json()["default_tax_regime"] == "new"
