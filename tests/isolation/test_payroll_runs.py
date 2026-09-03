import uuid
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TenantContext


def test_payroll_runs_are_tenant_isolated(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    # Company A creates a payroll run
    idempotency_key = f"iso-run-{uuid.uuid4()}"
    res_a = client.post(
        "/api/v1/payroll/runs",
        json={"month": 8, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": idempotency_key},
    )
    assert res_a.status_code == 202
    run_a_id = res_a.json()["id"]

    # Company B tries to view Company A's run detail -> 404 Not Found (due to RLS and tenant scoping)
    res_b_get = client.get(
        f"/api/v1/payroll/runs/{run_a_id}",
        headers=company_b.hr_headers,
    )
    assert res_b_get.status_code == 404

    # Company B tries to approve Company A's run -> 404 Not Found
    res_b_approve = client.post(
        f"/api/v1/payroll/runs/{run_a_id}/approve",
        headers=company_b.hr_headers,
    )
    assert res_b_approve.status_code == 404
