# ruff: noqa: F811, E501
"""Module 5, sub-feature 5.5 / 5.4: Payslip Email Notification Tests (B1-B7).

Tests for POST /api/v1/payroll/runs/{run_id}/send-payslips and payslip_email template.
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.email_templates import payslip_email
from app.core.rate_limit import limiter
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee
from app.modules.payroll.models import (
    PayrollRunStatus,
)
from app.modules.platform.models import AuditLog
from tests.conftest import TenantContext
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _make_run,
    _month_back,
    _staff,
    world,  # noqa: F401
)
from tests.rules.test_5_5_payslips import _released, _set_status


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def email_world(client: TestClient, db: Session, world, company_b: TenantContext) -> dict:
    w = dict(world)
    # world has 'emp' and 'manager'
    # Add a second regular employee e2
    e2 = _staff(client, db, world["ctx"], world["structure_id"])
    w["e1"] = world["emp"]
    w["e2"] = e2
    # Other company employee
    other_emp = _staff(client, db, company_b, None)
    w["other_emp"] = other_emp
    w["other_hr"] = company_b.hr_headers
    return w


def test_B1_template_content_and_safety():
    """B1: Template returns (subject, text, html).
    Subject names month & year.
    Body addresses employee by first name, states pay period, net pay, pay date,
    links to payslip in the app.
    NEVER includes bank account, PAN, Aadhaar, password.
    Gross, deductions and net are the only figures.
    """
    subject, text, html_body = payslip_email(
        first_name="Rohan",
        month_name="October",
        year=2026,
        pay_period="October 01, 2026 - October 31, 2026",
        pay_date="November 05, 2026",
        gross_pay=Decimal("100000.00"),
        deductions=Decimal("12000.00"),
        net_pay=Decimal("88000.00"),
        currency="INR",
        payslip_url="http://localhost:5173/payroll/payslip",
    )

    assert "October 2026" in subject
    assert "Rohan" in text and "Rohan" in html_body
    assert "October 01, 2026 - October 31, 2026" in text
    assert "November 05, 2026" in text
    assert "88000.00" in text
    assert "100000.00" in text
    assert "12000.00" in text
    assert "http://localhost:5173/payroll/payslip" in text
    assert "http://localhost:5173/payroll/payslip" in html_body

    # Safety checks: strictly forbid sensitive data in both subject and body
    combined = f"{subject} {text} {html_body}".lower()
    for sensitive_keyword in [
        "bank account",
        "account number",
        "ifsc",
        "pan",
        "aadhaar",
        "password",
    ]:
        assert sensitive_keyword not in combined, (
            f"Forbidden keyword '{sensitive_keyword}' found in email!"
        )


def test_B7_send_payslips_queues_selected_and_skips_unselected(
    client: TestClient, db: Session, email_world
):
    """B7.1: A run's payslips queue one email per selected employee and none for unselected."""
    world = email_world
    year, month = _month_back()
    run = _released(client, world, year, month)
    e1_id = world["e1"]["id"]

    with patch("app.workers.tasks.email.send_email_task.delay") as mock_send:
        resp = client.post(
            f"{RUNS}/{run['id']}/send-payslips",
            headers=world["hr1"],
            json={"employee_ids": [str(e1_id)]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_selected"] == 1
        assert data["queued_count"] == 1
        assert data["skipped_count"] == 0
        assert len(data["recipients"]) == 1
        assert data["recipients"][0]["employee_id"] == str(e1_id)
        assert data["recipients"][0]["status"] == "queued"
        assert mock_send.call_count == 1
        args, kwargs = mock_send.call_args
        bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
        emp1 = db.get(Employee, uuid.UUID(str(e1_id)))
        assert kwargs["to"] == emp1.email


def test_B7_send_payslips_skips_employee_with_no_email(
    client: TestClient, db: Session, email_world
):
    """B7.2: An employee with no email on file is skipped with a reason, and the rest still send."""
    world = email_world
    year, month = _month_back(2)
    run = _released(client, world, year, month)
    e1_id = world["e1"]["id"]
    e2_id = world["e2"]["id"]

    # Temporarily remove email from e2 in DB
    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    emp2 = db.get(Employee, uuid.UUID(str(e2_id)))
    assert emp2 is not None
    orig_email = emp2.email
    emp2.email = ""
    db.commit()

    try:
        with patch("app.workers.tasks.email.send_email_task.delay") as mock_send:
            resp = client.post(
                f"{RUNS}/{run['id']}/send-payslips",
                headers=world["hr1"],
                json={"employee_ids": [str(e1_id), str(e2_id)]},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["queued_count"] == 1
            assert data["skipped_count"] == 1
            e2_result = next(r for r in data["recipients"] if r["employee_id"] == str(e2_id))
            assert e2_result["status"] == "skipped"
            assert e2_result["reason"] == "No email address on file"
            assert mock_send.call_count == 1
    finally:
        bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
        emp2 = db.get(Employee, uuid.UUID(str(e2_id)))
        if emp2:
            emp2.email = orig_email
            db.commit()


def test_B7_send_payslips_permissions(client: TestClient, email_world):
    """B7.3: Manager gets 403, employee gets 403."""
    world = email_world
    year, month = _month_back(3)
    run = _released(client, world, year, month)

    resp_mgr = client.post(
        f"{RUNS}/{run['id']}/send-payslips",
        headers=world["manager"]["h"],
        json={"employee_ids": []},
    )
    assert resp_mgr.status_code == 403, resp_mgr.text

    resp_emp = client.post(
        f"{RUNS}/{run['id']}/send-payslips",
        headers=world["emp"]["h"],
        json={"employee_ids": []},
    )
    assert resp_emp.status_code == 403, resp_emp.text


def test_B7_send_payslips_cross_company_run_returns_404(client: TestClient, email_world):
    """B7.4: Another company's run_id returns 404."""
    world = email_world
    year, month = _month_back(4)
    run = _released(client, world, year, month)

    resp = client.post(
        f"{RUNS}/{run['id']}/send-payslips",
        headers=world["other_hr"],
        json={"employee_ids": []},
    )
    assert resp.status_code == 404, resp.text


def test_B7_send_payslips_cross_company_employee_rejected(client: TestClient, email_world):
    """B7.5: An employee_id from another company is rejected, not silently emailed."""
    world = email_world
    year, month = _month_back(5)
    run = _released(client, world, year, month)
    other_emp_id = world["other_emp"]["id"]

    with patch("app.workers.tasks.email.send_email_task.delay") as mock_send:
        resp = client.post(
            f"{RUNS}/{run['id']}/send-payslips",
            headers=world["hr1"],
            json={"employee_ids": [str(other_emp_id)]},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["queued_count"] == 0
        assert data["skipped_count"] == 1
        res = data["recipients"][0]
        assert res["employee_id"] == str(other_emp_id)
        assert res["status"] == "skipped"
        assert res["reason"] == "Employee not in this company"
        assert mock_send.call_count == 0


def test_B7_send_payslips_unapproved_run_returns_409(client: TestClient, db: Session, email_world):
    """B7.6: Sending for a run in a state without payslips returns 409."""
    world = email_world
    year, month = _month_back(6)
    run = _make_run(client, world["hr1"], year, month)
    _set_status(db, world, run["id"], PayrollRunStatus.draft)

    resp = client.post(
        f"{RUNS}/{run['id']}/send-payslips",
        headers=world["hr1"],
        json={"employee_ids": []},
    )
    assert resp.status_code == 409, resp.text
    err_body = str(resp.json()).lower()
    assert "draft" in err_body or "payslips" in err_body


def test_B7_send_payslips_reports_delivery_console(client: TestClient, email_world):
    """B7.7: Response reports delivery 'console' when EMAIL_BACKEND is console."""
    world = email_world
    year, month = _month_back(7)
    run = _released(client, world, year, month)

    with patch("app.workers.tasks.email.send_email_task.delay"):
        resp = client.post(
            f"{RUNS}/{run['id']}/send-payslips",
            headers=world["hr1"],
            json={"employee_ids": []},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["delivery"] == "console"


def test_B7_send_payslips_audit_row_and_safe_details(client: TestClient, db: Session, email_world):
    """B7.8: Audit row exists with run id and recipient ids, containing no email address or body."""
    world = email_world
    year, month = _month_back(8)
    run = _released(client, world, year, month)
    e1_id = world["e1"]["id"]

    with patch("app.workers.tasks.email.send_email_task.delay"):
        resp = client.post(
            f"{RUNS}/{run['id']}/send-payslips",
            headers=world["hr1"],
            json={"employee_ids": [str(e1_id)]},
        )
        assert resp.status_code == 200, resp.text

    bind_tenant_to_session(db, company_id=world["ctx"].company_id, is_platform_admin=False)
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == world["ctx"].company_id,
            AuditLog.action == "PAYSLIPS_EMAILED",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.entity_id == uuid.UUID(run["id"])
    details = audit.details or {}
    assert details.get("run_id") == str(run["id"])
    assert details.get("count") == 1
    assert str(e1_id) in details.get("recipient_employee_ids", [])
    # Verify no email addresses, bodies or subjects leaked into audit details
    details_str = str(details).lower()
    assert "@" not in details_str
    assert "body" not in details_str
    assert "subject" not in details_str
