"""`notifications` is RLS-protected and already covered by the parametrized
sweep in test_rls_policies.py with zero edits to that file. `audit_logs` has
no RLS at all (Spec 7.8) — its only protection is AuditRepository's explicit
`company_id` filter, so this is the one HTTP-level proof the spec's own
"why no RLS here" note calls for: company B's HR admin must never see one of
company A's audit rows.
"""

import uuid


def test_audit_logs_are_company_scoped_even_without_rls(client, company_a, company_b):
    created = client.post(
        "/api/v1/employees",
        headers=company_a.hr_headers,
        json={
            "first_name": "Isolated",
            "email": f"{uuid.uuid4().hex[:10]}@auditiso.com",
            "hire_date": "2024-01-01",
        },
    )
    assert created.status_code == 201, created.text

    company_a_logs = client.get("/api/v1/audit-logs", headers=company_a.hr_headers)
    assert company_a_logs.status_code == 200
    assert company_a_logs.json()["total"] >= 1

    company_b_logs = client.get("/api/v1/audit-logs", headers=company_b.hr_headers)
    assert company_b_logs.status_code == 200
    assert company_b_logs.json()["items"] == []

    a_ids = {row["id"] for row in company_a_logs.json()["items"]}
    b_ids = {row["id"] for row in company_b_logs.json()["items"]}
    assert a_ids.isdisjoint(b_ids)
