"""Tests for Part P (5.10 mark payroll run as paid).

Rules:
1. A run that is draft, processing or rejected returns 409 on POST /payroll/runs/{id}/payments.
2. An item marked failed can later be marked paid, and ends with payment_status "paid".
3. The run status becomes "paid" only when EVERY item is paid: mark all but one, assert run
   is still "approved"; mark the last, assert run is "paid".
4. Validation:
   - paid_on in the future is rejected (422)
   - paid_on earlier than the run's approval date is rejected (422)
   - a bank_reference over max length (64 chars) is rejected (422)
   - a bank_reference containing a control character is rejected (422)
5. Audit: after a successful call, query the audit_logs row for action PAYROLL_PAYMENT_RECORDED
   and assert its details contain run_id, item_ids and fields_changed, and that the serialised
   details contain NO net_salary, no amount, and not the bank_reference value sent. Assert exactly
   one audit row per call.
6. Notification: assert one PAYROLL_PAID notification exists for each employee marked paid, and
   none for employees left pending.
7. Rate limit: 429 on POST /payroll/runs/{id}/payments using the shared limits_on fixture.
8. Cross-company: company B's owner calling company A's payments route gets 404, not 403.
9. Payment CSV unchanged: generate before and after recording payments and assert bytes identical.
"""

import json
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import UserRole
from app.modules.payroll.models import PayrollItem, PayrollRun, PayrollRunStatus
from app.modules.platform.models import AuditLog, Notification
from tests.conftest import TenantContext
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _filled_world,
    _make_run,
)
from tests.rules.test_5_4_payroll_runs import (
    world as world,
)
from tests.rules.test_5_5_payslips import _set_status
from tests.rules.test_5_8_bank_accounts import _file_url


def _setup_approved_run(
    client: TestClient, db: Session, w: dict
) -> tuple[PayrollRun, list[PayrollItem]]:
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
    r_emp = client.post(url, json=payload, headers=world["emp"]["h"])
    assert r_emp.status_code in (401, 403)

    # Manager
    r_mgr = client.post(url, json=payload, headers=world["manager"]["h"])
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


def test_1_run_not_approved_returns_409(client: TestClient, db: Session, world: dict):
    """1. A run that is draft, processing or failed/unapproved returns 409 on POST payments."""
    _filled_world(db, world)
    run_json = _make_run(client, world["hr1"], world["year"], world["month"])
    run_id = run_json["id"]
    items = db.query(PayrollItem).filter(PayrollItem.payroll_run_id == uuid.UUID(run_id)).all()
    assert len(items) >= 1
    url = f"/api/v1/payroll/runs/{run_id}/payments"
    payload = {"payments": [{"item_id": str(items[0].id), "status": "paid"}]}

    # Current status is pending_approval -> 409
    r_pending = client.post(url, json=payload, headers=world["hr1"])
    assert r_pending.status_code == 409, f"Pending run must get 409: {r_pending.text}"

    # Set status to draft -> 409
    _set_status(db, world, run_id, PayrollRunStatus.draft)
    r_draft = client.post(url, json=payload, headers=world["hr1"])
    assert r_draft.status_code == 409, f"Draft run must get 409: {r_draft.text}"

    # Set status to processing -> 409
    _set_status(db, world, run_id, PayrollRunStatus.processing)
    r_proc = client.post(url, json=payload, headers=world["hr1"])
    assert r_proc.status_code == 409, f"Processing run must get 409: {r_proc.text}"

    # Set status to failed -> 409
    _set_status(db, world, run_id, PayrollRunStatus.failed)
    r_failed = client.post(url, json=payload, headers=world["hr1"])
    assert r_failed.status_code == 409, f"Failed run must get 409: {r_failed.text}"


def test_2_failed_item_can_later_be_marked_paid(client: TestClient, db: Session, world: dict):
    """2. An item marked failed can later be marked paid, and ends with payment_status 'paid'."""
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()

    # Step 1: mark as failed
    p_fail = {
        "payments": [
            {
                "item_id": str(items[0].id),
                "status": "failed",
                "bank_reference": "FAIL_REF_1",
            }
        ]
    }
    r1 = client.post(url, json=p_fail, headers=world["hr1"])
    assert r1.status_code == 200, r1.text
    db.refresh(items[0])
    assert items[0].payment_status == "failed"
    assert items[0].paid_on is None
    assert items[0].bank_reference == "FAIL_REF_1"

    # Step 2: later mark as paid
    p_paid = {
        "payments": [
            {
                "item_id": str(items[0].id),
                "status": "paid",
                "paid_on": today_utc.isoformat(),
                "bank_reference": "PAID_REF_2",
            }
        ]
    }
    r2 = client.post(url, json=p_paid, headers=world["hr1"])
    assert r2.status_code == 200, r2.text
    db.refresh(items[0])
    assert items[0].payment_status == "paid"
    assert items[0].paid_on == today_utc
    assert items[0].bank_reference == "PAID_REF_2"


def test_3_run_status_becomes_paid_only_when_every_item_is_paid(
    client: TestClient, db: Session, world: dict
):
    """3. The run status becomes 'paid' only when EVERY item is paid:
    mark all but one, assert run is still 'approved'; mark the last, assert run is 'paid'.
    """
    run, items = _setup_approved_run(client, db, world)
    assert len(items) >= 2, "Test requires at least 2 items in run"
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()

    # Mark all but the last item as paid
    first_batch = [
        {
            "item_id": str(item.id),
            "status": "paid",
            "paid_on": today_utc.isoformat(),
            "bank_reference": f"REF_{idx}",
        }
        for idx, item in enumerate(items[:-1])
    ]
    r1 = client.post(url, json={"payments": first_batch}, headers=world["hr1"])
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == PayrollRunStatus.approved.value
    db.refresh(run)
    assert run.status == PayrollRunStatus.approved

    # Now mark the last item as paid
    last_batch = [
        {
            "item_id": str(items[-1].id),
            "status": "paid",
            "paid_on": today_utc.isoformat(),
            "bank_reference": "LAST_REF",
        }
    ]
    r2 = client.post(url, json={"payments": last_batch}, headers=world["hr1"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == PayrollRunStatus.paid.value
    db.refresh(run)
    assert run.status == PayrollRunStatus.paid


def test_4_validation_dates_and_bank_reference(client: TestClient, db: Session, world: dict):
    """4. Validation, each its own assertion:
    - paid_on in the future is rejected (422)
    - paid_on earlier than the run's approval date is rejected (422)
    - a bank_reference over the max length (64) is rejected (422)
    - a bank_reference containing a control character is rejected (422)
    """
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()
    item_id = str(items[0].id)

    # 4a: paid_on in future
    future_date = today_utc + timedelta(days=2)
    r_future = client.post(
        url,
        json={
            "payments": [{"item_id": item_id, "status": "paid", "paid_on": future_date.isoformat()}]
        },
        headers=world["hr1"],
    )
    assert r_future.status_code == 422, f"Future paid_on must get 422: {r_future.text}"

    # 4b: paid_on earlier than run approval date
    approved_date = run.approved_at.date() if run.approved_at else today_utc
    past_date = approved_date - timedelta(days=5)
    r_past = client.post(
        url,
        json={
            "payments": [{"item_id": item_id, "status": "paid", "paid_on": past_date.isoformat()}]
        },
        headers=world["hr1"],
    )
    assert r_past.status_code == 422, f"Past paid_on must get 422: {r_past.text}"

    # 4c: bank_reference over max length (65 chars > max_length=64)
    long_ref = "A" * 65
    r_long = client.post(
        url,
        json={"payments": [{"item_id": item_id, "status": "paid", "bank_reference": long_ref}]},
        headers=world["hr1"],
    )
    assert r_long.status_code == 422, f"Over-length bank_ref must get 422: {r_long.text}"

    # 4d: bank_reference with control characters (e.g. null byte \x00, bell \x07, escape \x1b)
    ctrl_ref = "UTR123\x00456"
    r_ctrl = client.post(
        url,
        json={"payments": [{"item_id": item_id, "status": "paid", "bank_reference": ctrl_ref}]},
        headers=world["hr1"],
    )
    assert r_ctrl.status_code == 422, f"Control char in bank_ref must get 422: {r_ctrl.text}"


def test_5_audit_logs_record_clean_details(client: TestClient, db: Session, world: dict):
    """5. Audit: after a successful call, query audit_logs row for PAYROLL_PAYMENT_RECORDED
    and assert its details contain run_id, item_ids and fields_changed, and that the
    serialised details contain NO net_salary, no amount, and not the bank_reference value sent.
    Assert exactly one audit row per call.
    """
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()
    sent_ref = "UTR_SUPER_SECRET_REF_999"
    payload = {
        "payments": [
            {
                "item_id": str(items[0].id),
                "status": "paid",
                "paid_on": today_utc.isoformat(),
                "bank_reference": sent_ref,
            }
        ]
    }
    r = client.post(url, json=payload, headers=world["hr1"])
    assert r.status_code == 200, r.text

    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "payroll_run",
            AuditLog.entity_id == run.id,
            AuditLog.action == "PAYROLL_PAYMENT_RECORDED",
        )
        .all()
    )
    assert len(audit_rows) == 1, f"Expected exactly 1 audit row, found {len(audit_rows)}"
    log = audit_rows[0]
    details = log.details or {}
    assert "run_id" in details
    assert "item_ids" in details
    assert "fields_changed" in details
    assert details["run_id"] == str(run.id)
    assert str(items[0].id) in details["item_ids"]

    # Verify serialized details do not leak sensitive numbers or reference
    serialized = json.dumps(details).lower()
    assert "net_salary" not in serialized
    assert "amount" not in serialized
    assert sent_ref.lower() not in serialized


def test_6_notifications_sent_only_for_paid_employees(client: TestClient, db: Session, world: dict):
    """6. Notification: assert one PAYROLL_PAID notification exists for each employee marked paid,
    and none for employees left pending.
    """
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    today_utc = utcnow().date()
    paid_item = items[0]
    pending_item = items[1]

    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    # Clear preexisting notifications
    db.query(Notification).filter(Notification.type == "PAYROLL_PAID").delete()
    db.commit()

    payload = {
        "payments": [
            {
                "item_id": str(paid_item.id),
                "status": "paid",
                "paid_on": today_utc.isoformat(),
                "bank_reference": "UTR_NOTIF",
            }
        ]
    }
    r = client.post(url, json=payload, headers=world["hr1"])
    assert r.status_code == 200, r.text

    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    notifs = db.query(Notification).filter(Notification.type == "PAYROLL_PAID").all()
    assert len(notifs) == 1
    assert notifs[0].entity_id == run.id

    # The recipient user must belong to paid_item.employee_id
    paid_user_id = db.execute(
        text("SELECT user_id FROM employees WHERE id = :e"),
        {"e": paid_item.employee_id},
    ).scalar_one_or_none()
    assert paid_user_id is not None
    assert notifs[0].user_id == paid_user_id

    # Pending employee must have 0 PAYROLL_PAID notifications
    pending_user_id = db.execute(
        text("SELECT user_id FROM employees WHERE id = :e"),
        {"e": pending_item.employee_id},
    ).scalar_one_or_none()
    if pending_user_id:
        pending_notifs = (
            db.query(Notification)
            .filter(
                Notification.type == "PAYROLL_PAID",
                Notification.user_id == pending_user_id,
            )
            .all()
        )
        assert len(pending_notifs) == 0


def test_7_rate_limit_on_payments(client: TestClient, db: Session, world: dict, limits_on):
    """7. Rate limit: 429 on POST /payroll/runs/{id}/payments using shared limits_on fixture."""
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    limiter.reset()

    # Route limit is 30/minute. 35 calls must trigger 429.
    responses = []
    payload = {"payments": [{"item_id": str(items[0].id), "status": "failed"}]}
    for _ in range(35):
        resp = client.post(url, json=payload, headers=world["hr1"])
        responses.append(resp.status_code)

    assert 429 in responses, f"Expected 429 in responses: {responses}"


def test_8_cross_company_returns_404(
    client: TestClient, db: Session, world: dict, company_b: TenantContext
):
    """8. Cross-company: company B's owner calling company A's payments route gets 404, not 403."""
    run, items = _setup_approved_run(client, db, world)
    url = f"/api/v1/payroll/runs/{run.id}/payments"
    payload = {"payments": [{"item_id": str(items[0].id), "status": "paid"}]}

    owner_b_headers, _ = _extra_user(db, company_b.company_id, UserRole.owner)
    resp = client.post(url, json=payload, headers=owner_b_headers)
    assert resp.status_code == 404, f"Cross-company must return 404, got {resp.status_code}"
    missing_url = f"/api/v1/payroll/runs/{uuid.uuid4()}/payments"
    missing = client.post(missing_url, json=payload, headers=owner_b_headers)
    assert missing.status_code == 404
    assert resp.json()["error"]["message"] == missing.json()["error"]["message"]


def test_9_payment_csv_unchanged_after_recording_payments(
    client: TestClient, db: Session, world: dict
):
    """9. The 5.8 payment CSV is unchanged: generate before and after recording payments
    on the same run and assert the bytes are identical.
    """
    from tests.rules.test_5_8_bank_accounts import _body, _for

    # Setup world with bank details so payment file can be generated
    _filled_world(db, world)
    for who in ("emp", "manager"):
        client.put(_for(world[who]["id"]), json=_body(), headers=world["hr1"])

    run_json = _make_run(client, world["hr1"], world["year"], world["month"])
    run_id = run_json["id"]
    appr = client.post(f"{RUNS}/{run_id}/approve", headers=world["owner"])
    assert appr.status_code == 200, appr.text

    # Generate CSV before recording payments
    file_url = _file_url(run_id)
    r_before = client.get(file_url, headers=world["hr1"])
    assert r_before.status_code == 200, f"Payment file fetch failed: {r_before.text}"
    bytes_before = r_before.content

    # Record payment for an item
    run = db.get(PayrollRun, uuid.UUID(run_id))
    items = db.query(PayrollItem).filter(PayrollItem.payroll_run_id == run.id).all()
    today_utc = utcnow().date()
    p_url = f"/api/v1/payroll/runs/{run_id}/payments"
    p_resp = client.post(
        p_url,
        json={
            "payments": [
                {
                    "item_id": str(items[0].id),
                    "status": "paid",
                    "paid_on": today_utc.isoformat(),
                    "bank_reference": "UTR_CSV_TEST",
                }
            ]
        },
        headers=world["hr1"],
    )
    assert p_resp.status_code == 200, p_resp.text

    # Generate CSV after recording payments
    r_after = client.get(file_url, headers=world["hr1"])
    assert r_after.status_code == 200, f"Payment file fetch after failed: {r_after.text}"
    bytes_after = r_after.content

    assert bytes_before == bytes_after, (
        "Payment CSV bytes must be completely unchanged by payment recording"
    )
