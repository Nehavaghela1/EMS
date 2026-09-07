import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TenantContext


def test_performance_cycles_and_goals_are_tenant_isolated(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    # 1. Company A creates a performance cycle
    cycle_res = client.post(
        "/api/v1/performance/cycles",
        json={
            "name": "Company A Cycle",
            "cycle_type": "annual",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        headers=company_a.hr_headers,
    )
    assert cycle_res.status_code == 201
    cycle_id = cycle_res.json()["id"]

    # 2. Company B attempts to update / activate Company A's cycle -> 404 Not Found
    act_res = client.put(
        f"/api/v1/performance/cycles/{cycle_id}",
        json={"status": "active"},
        headers=company_b.hr_headers,
    )
    assert act_res.status_code == 404

    # 3. Company B lists cycles -> sees 0 cycles
    list_res = client.get("/api/v1/performance/cycles", headers=company_b.hr_headers)
    assert list_res.status_code == 200
    b_cycles = list_res.json()["items"]
    assert not any(c["id"] == cycle_id for c in b_cycles)
