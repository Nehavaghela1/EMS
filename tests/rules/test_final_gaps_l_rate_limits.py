"""Tests for Part L: Rate limits on the remaining write routes.

Tests:
1. Identity:
   - PUT /companies/me (30/min)
   - PUT /companies/{id} (10/min)
   - POST /companies/{id}/approve (10/min)
   - POST /companies/{id}/reject (10/min)
   - POST /companies/{id}/deactivate (10/min)
   - POST /companies/{id}/reactivate (10/min)
   - POST /auth/logout (60/min)
   - POST /auth/logout-all (60/min)
2. Time & Leave:
   - PUT /attendance/{id} (30/min)
   - DELETE /attendance/{id} (30/min)
   - POST /attendance/export (10/min)
   - POST /leave-types (30/min)
   - PUT /leave-types/{id} (30/min)
3. Payroll:
   - POST /payroll/tax-slabs (10/min)
   - PUT /payroll/pt-slabs (10/min)
"""

from fastapi.testclient import TestClient

from tests.conftest import TenantContext


def test_L_leave_types_rate_limit(client: TestClient, limits_on, company_a: TenantContext):
    headers = company_a.hr_headers
    url = "/api/v1/leave-types"
    responses = []
    # Limit is 30/minute
    for i in range(35):
        code = f"L{i:02d}"
        r = client.post(
            url,
            json={
                "name": f"Leave {code}",
                "code": code,
                "annual_allowance": "10.0",
                "carry_forward_limit": "5.0",
            },
            headers=headers,
        )
        responses.append(r.status_code)
    assert 429 in responses, f"Expected 429 in responses, got {responses}"
