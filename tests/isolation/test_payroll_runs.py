import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from tests.conftest import TenantContext


def test_payroll_runs_are_tenant_isolated(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    # A run needs the platform rates in force for its month (5.2)
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    seed_statutory_rates(db)
    # Company A creates a payroll run
    idempotency_key = f"iso-run-{uuid.uuid4()}"
    res_a = client.post(
        "/api/v1/payroll/runs",
        json={"month": 8, "year": 2026, "run_type": "regular"},
        headers={**company_a.hr_headers, "Idempotency-Key": idempotency_key},
    )
    assert res_a.status_code == 202
    run_a_id = res_a.json()["id"]

    # Company B tries to view Company A's run detail -> 404 Not Found
    # (due to RLS and tenant scoping)
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
