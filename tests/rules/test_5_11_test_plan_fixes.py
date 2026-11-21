# ruff: noqa: F401, F811  (pytest fixtures imported from a sibling test module)
"""Module 5 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-052  a payroll run request without an Idempotency-Key gets the standard error envelope
"""

from tests.rules.test_5_4_payroll_runs import RUNS, world


def test_missing_idempotency_key_uses_the_error_envelope(client, db, world) -> None:
    resp = client.post(
        RUNS, json={"month": world["month"], "year": world["year"]}, headers=world["hr1"]
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" not in body
    assert body["error"]["code"] == "idempotency_key_required"
    assert body["error"]["message"] == "Idempotency-Key header is required."
    assert body["error"]["request_id"]
