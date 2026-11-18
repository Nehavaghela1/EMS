"""Red-first tests for Part P (5.10 mark payroll run as paid).

P1. PayrollItem fields: payment_status ("pending"|"paid"|"failed"), paid_on (date|None), bank_reference (str|None).
P2. POST /payroll/runs/{id}/payments endpoint exists and updates payment status.
P3. 403 for employee, manager, and super_admin (only owner & HR admin allowed).
P4. 409 if run is draft (not approved).
P5. Run status transitions to "paid" if and only if all items are "paid".
P6. Failed items can later be marked paid.
P7. Already-paid items cannot be modified (returns 409).
P8. Validation: paid_on not in future (UTC), not before run approval; bank_reference regex / max length.
P9. Audit: exactly one audit record with IDs and field names only (no bank details, no amounts).
P10. Notifications sent to employees whose items were marked paid.
"""

from datetime import date, timedelta
from decimal import Decimal
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.payroll.models import PayrollRun, PayrollRunStatus, PayrollItem
from app.modules.platform.models import AuditLog, Notification
from tests.conftest import TenantContext
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _fill,
    _filled_world,
    _make_run,
    _month_back,
    _staff,
    _structure,
    world,
)


def _setup_approved_run(client: TestClient, db: Session, w: dict) -> tuple[PayrollRun, list[PayrollItem]]:
    _filled_world(db, w)
    run_json = _make_run(client, w["hr1"], w["year"], w["month"])
    run_id = run_json["id"]
    appr = client.post(f"{RUNS}/{run_id}/approve", headers=w["owner"])
    assert appr.status_code == 200, appr.text
    run = db.get(PayrollRun, uuid.UUID(run_id))
    items = db.query(PayrollItem).filter(PayrollItem.payroll_run_id == run.id).all()
    return run, items


def test_P1_P2_record_payment_happy_path(client: TestClient, db: Session, world: dict):
    run, items = _setup_approved_run(client, db, world)
    assert len(items) >= 1

    # Check P1 fields exist on model
    assert hasattr(items[0], "payment_status"), "P1: PayrollItem must have payment_status"
    assert hasattr(items[0], "paid_on"), "P1: PayrollItem must have paid_on"
    assert hasattr(items[0], "bank_reference"), "P1: PayrollItem must have bank_reference"

    # Call endpoint to record payment
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()
    payload = {
        "payments": [
            {
                "item_id": str(items[0].id),
                "status": "paid",
                "paid_on": today_utc.isoformat(),
                "bank_reference": "UTR123456789",
            }
        ]
    }
    resp = client.post(url, json=payload, headers=world["hr1"])
    assert resp.status_code == 200, resp.text

    db.refresh(items[0])
    assert items[0].payment_status == "paid"
    assert items[0].paid_on == today_utc
    assert items[0].bank_reference == "UTR123456789"


def test_P3_payments_forbidden_for_employee_manager_superadmin(
    client: TestClient, db: Session, world: dict, super_admin_headers: dict
):
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    payload = {"payments": [{"item_id": str(items[0].id), "status": "paid"}]}

    # Employee
    r_emp = client.post(url, json=payload, headers=world["emp"]["headers"])
    assert r_emp.status_code in (401, 403)

    # Manager
    r_mgr = client.post(url, json=payload, headers=world["manager"]["headers"])
    assert r_mgr.status_code in (401, 403)

    # Super admin
    r_sa = client.post(url, json=payload, headers=super_admin_headers)
    assert r_sa.status_code in (401, 403)


def test_P7_already_paid_cannot_be_modified(client: TestClient, db: Session, world: dict):
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()

    payload = {
        "payments": [
            {
                "item_id": str(items[0].id),
                "status": "paid",
                "paid_on": today_utc.isoformat(),
                "bank_reference": "UTR111",
            }
        ]
    }
    r1 = client.post(url, json=payload, headers=world["hr1"])
    assert r1.status_code == 200

    # Second attempt to modify an already paid item -> 409
    payload2 = {
        "payments": [
            {
                "item_id": str(items[0].id),
                "status": "failed",
            }
        ]
    }
    r2 = client.post(url, json=payload2, headers=world["hr1"])
    assert r2.status_code == 409
