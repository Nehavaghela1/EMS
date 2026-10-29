import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus, ResignationStatus
from app.modules.identity.models import RefreshToken, User, UserRole
from app.modules.platform.models import AuditLog
from tests.rules.test_2_6_exit import _auth_headers

pytest_plugins = ["tests.rules.test_2_6_exit"]


def _create_user_and_employee(
    db: Session,
    company_id: uuid.UUID,
    role: UserRole,
    email: str | None = None,
    first_name: str = "Test",
    last_name: str = "User",
) -> tuple[User, Employee]:
    email = email or f"user-{uuid.uuid4().hex[:6]}@example.com"
    user = User(
        id=uuid.uuid4(),
        company_id=company_id,
        email=email,
        hashed_password=hash_password("Pass1234!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    emp = Employee(
        id=uuid.uuid4(),
        company_id=company_id,
        user_id=user.id,
        employee_code=f"EMP{uuid.uuid4().hex[:4].upper()}",
        first_name=first_name,
        last_name=last_name,
        email=email,
        hire_date=date(2023, 1, 1),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        is_active=True,
        level="L1",
        notice_period_days=30,
    )
    db.add(emp)
    db.commit()
    return user, emp


def test_f01_zero_notice_period_days(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F1: Notice of 0 is legal (0 to 365).
    An employee with notice 0 who resigns with last working date today has
    shortfall 0, recovery 0; settlement shows notice required 0.
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    # Create employee with notice_period_days = 0
    emp_user, emp = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"zero-notice-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp.notice_period_days = 0
    db.commit()

    emp_headers = _auth_headers(emp_user)

    # Resign with LWD = today
    r_sub = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={
            "resignation_date": str(today),
            "last_working_date": str(today),
            "reason": "Immediate departure with 0 notice",
        },
    )
    assert r_sub.status_code == 200, r_sub.text
    sub_data = r_sub.json()
    assert sub_data["notice_period_days"] == 0
    assert sub_data["notice_recovery_days"] == 0

    # Approve resignation
    r_app = client.put(
        f"/api/v1/employees/{emp.id}/resignation/approve",
        headers=hr_headers,
        json={"approved": True},
    )
    assert r_app.status_code == 200, r_app.text
    app_data = r_app.json()
    assert app_data["notice_recovery_days"] == 0

    # View settlement: notice required = 0, notice recovery = 0
    r_fnf = client.get(f"/api/v1/employees/{emp.id}/fnf", headers=hr_headers)
    assert r_fnf.status_code == 200, r_fnf.text
    fnf_data = r_fnf.json()
    assert fnf_data["notice_days_required"] == 0
    assert fnf_data["notice_recovery_days"] == 0
    assert Decimal(str(fnf_data["notice_recovery_amount"])) == Decimal("0.00")


def test_f02_settlement_turns_access_off(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F2: Settle on last working date (before scheduled job runs):
    user is inactive, refresh tokens revoked, API call with old access token gets 401.
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    emp_user, emp = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"settle-off-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp.hire_date = today - timedelta(days=100)
    emp.is_active = True
    db.commit()

    emp_headers = _auth_headers(emp_user)

    # 1. Employee has an active refresh token
    from app.core.security import generate_refresh_token, hash_token
    from app.core.time import utcnow

    raw_token = generate_refresh_token()
    token_rec = RefreshToken(
        id=uuid.uuid4(),
        user_id=emp_user.id,
        token_hash=hash_token(raw_token),
        expires_at=utcnow() + timedelta(days=7),
        is_revoked=False,
    )
    db.add(token_rec)
    db.commit()

    # Verify old token works initially
    r_self_before = client.get(f"/api/v1/employees/{emp.id}", headers=emp_headers)
    assert r_self_before.status_code == 200

    # Resign and approve with LWD = today
    r_res = client.post(
        f"/api/v1/employees/{emp.id}/resignation",
        headers=emp_headers,
        json={
            "resignation_date": str(today),
            "last_working_date": str(today),
            "reason": "Settlement test",
        },
    )
    assert r_res.status_code == 200

    r_app = client.put(
        f"/api/v1/employees/{emp.id}/resignation/approve",
        headers=hr_headers,
        json={"approved": True},
    )
    assert r_app.status_code == 200

    # Sign off all 3 clearances
    for flag in ["it_clearance", "hr_clearance", "finance_clearance"]:
        r_sign = client.put(
            f"/api/v1/employees/{emp.id}/fnf/clearance",
            headers=hr_headers,
            json={flag: True},
        )
        assert r_sign.status_code == 200

    # Settle
    r_settle = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={"mark_settled": True},
    )
    assert r_settle.status_code == 200

    # Verify user is inactive and tokens revoked
    db.refresh(emp)
    db.refresh(emp_user)
    assert emp.is_active is False
    assert emp_user.is_active is False

    db.refresh(token_rec)
    assert token_rec.is_revoked is True

    # Check EMPLOYEE_EXIT_APPLIED audit row exists
    audit_exit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_EXIT_APPLIED",
            AuditLog.entity_id == emp.id,
        )
        .first()
    )
    assert audit_exit is not None

    # Old access token must get 401
    r_self_after = client.get(f"/api/v1/employees/{emp.id}", headers=emp_headers)
    assert r_self_after.status_code == 401, f"Expected 401, got {r_self_after.status_code}"


def test_f03_apply_exit_commit_flag_and_atomicity(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F3:
    - apply_exit idempotent: calling twice writes exactly one EMPLOYEE_EXIT_APPLIED row.
    - If audit write fails inside terminate-today (patch it to raise), employee stays active with
      unchanged status (single transaction rollback).
    """
    from app.modules.hr.service import EmployeeService

    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    emp_user, emp = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"f3-idemp-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp.is_active = True
    db.commit()

    # Call apply_exit first time
    service = EmployeeService(db)
    res1 = service.apply_exit(cid, emp.id, actor=None, commit=True)
    assert res1 is not None

    # Count audit rows
    count1 = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_EXIT_APPLIED",
            AuditLog.entity_id == emp.id,
        )
        .count()
    )
    assert count1 == 1

    # Call apply_exit second time (employee already inactive, user inactive, no tokens)
    res2 = service.apply_exit(cid, emp.id, actor=None, commit=True)
    assert res2 is not None

    count2 = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_EXIT_APPLIED",
            AuditLog.entity_id == emp.id,
        )
        .count()
    )
    assert count2 == 1, "Idempotent apply_exit must not write a duplicate audit row"

    # Part 2: Atomicity on terminate-today failure
    emp_user2, emp2 = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"f3-atom-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp2.is_active = True
    db.commit()

    with patch(
        "app.modules.platform.service.AuditService.record",
        side_effect=RuntimeError("Simulated audit write failure"),
    ):
        with pytest.raises(RuntimeError):
            client.post(
                f"/api/v1/employees/{emp2.id}/terminate",
                headers=hr_headers,
                json={
                    "termination_date": str(today),
                    "reason": "Test atomicity rollback",
                },
            )

    db.refresh(emp2)
    db.refresh(emp_user2)
    assert emp2.is_active is True
    assert emp_user2.is_active is True
    assert emp2.resignation_status == ResignationStatus.none


def test_f04_audit_money_changes_and_clearance_flags(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F4:
    - Changing severance, reimbursements, gratuity, or asset deductions writes FNF_AMOUNTS_UPDATED
      per request with field names only (never amounts).
    - CLEARANCE_UPDATED row written when flags change in same request that settles.
    - No amount values appear in any audit details.
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    emp_user, emp = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"f4-audit-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp.is_active = True
    emp.resignation_status = ResignationStatus.approved
    emp.last_working_date = today
    db.commit()

    # 1. Update amounts
    r_amt = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={
            "severance_pay": "50000.00",
            "pending_reimbursements": "12000.00",
            "gratuity_bonus": "25000.00",
            "asset_deductions": "3000.00",
        },
    )
    assert r_amt.status_code == 200, r_amt.text

    audit_amounts = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "FNF_AMOUNTS_UPDATED",
            AuditLog.entity_id == emp.id,
        )
        .first()
    )
    assert audit_amounts is not None, "FNF_AMOUNTS_UPDATED audit log must be recorded"
    details_str = str(audit_amounts.details)
    assert "50000" not in details_str
    assert "12000" not in details_str
    assert "25000" not in details_str
    assert "3000" not in details_str
    fields_updated = audit_amounts.details.get("fields", [])
    assert "severance_pay" in fields_updated
    assert "pending_reimbursements" in fields_updated
    assert "gratuity_bonus" in fields_updated
    assert "asset_deductions" in fields_updated

    # 2. Update clearance flags AND mark_settled in the same request
    r_settle_both = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_headers,
        json={
            "it_clearance": True,
            "hr_clearance": True,
            "finance_clearance": True,
            "mark_settled": True,
        },
    )
    assert r_settle_both.status_code == 200, r_settle_both.text

    # Both CLEARANCE_UPDATED and FNF_SETTLED must exist
    audit_clr = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "CLEARANCE_UPDATED",
            AuditLog.entity_id == emp.id,
        )
        .first()
    )
    assert audit_clr is not None, (
        "CLEARANCE_UPDATED must be recorded even when settling in same call"
    )

    audit_settle = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "FNF_SETTLED",
            AuditLog.entity_id == emp.id,
        )
        .first()
    )
    assert audit_settle is not None


def test_f05_queue_paging_validation(client: TestClient, exit_setup: dict[str, Any]) -> None:
    """F5: GET /employees/clearance-queue paging validation:
    - page=0, page=-1, limit=0, limit=101 give 422
    - limit=100 works
    - page past the end returns empty list with 200.
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])

    assert (
        client.get("/api/v1/employees/clearance-queue?page=0", headers=hr_headers).status_code
        == 422
    )
    assert (
        client.get("/api/v1/employees/clearance-queue?page=-1", headers=hr_headers).status_code
        == 422
    )
    assert (
        client.get("/api/v1/employees/clearance-queue?limit=0", headers=hr_headers).status_code
        == 422
    )
    assert (
        client.get("/api/v1/employees/clearance-queue?limit=101", headers=hr_headers).status_code
        == 422
    )

    r_100 = client.get("/api/v1/employees/clearance-queue?limit=100&page=1", headers=hr_headers)
    assert r_100.status_code == 200

    r_past = client.get("/api/v1/employees/clearance-queue?page=9999", headers=hr_headers)
    assert r_past.status_code == 200
    assert r_past.json()["items"] == []


def test_f06_notice_defaults_fallback_and_put_shape(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F6:
    - No company default set gives 30 for L1, L2, L3 and for a probation employee.
    - Explicit value wins.
    - After PUT L3=90 a new L3 employee gets 90 and existing employee is unchanged.
    - Partial PUT body gives 422.
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])
    today = date.today()

    # Clear company notice defaults
    company = exit_setup["company_a"]
    company.notice_period_defaults = None
    db.commit()

    # Partial PUT body gives 422
    r_partial = client.put(
        "/api/v1/companies/notice-period-defaults",
        headers=hr_headers,
        json={"L1": 45},
    )
    assert r_partial.status_code == 422

    # Creation when defaults are unset -> 30 for L1, L2, L3 and probation
    for lvl in ["L1", "L2", "L3"]:
        emp_p = {
            "first_name": f"Def{lvl}",
            "email": f"def-{lvl}-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": str(today),
            "level": lvl,
        }
        res = client.post("/api/v1/employees", headers=hr_headers, json=emp_p)
        assert res.status_code == 201
        assert res.json()["notice_period_days"] == 30, f"Expected 30 for unset default {lvl}"

    # Probation employee with unset defaults gets 30 (not 15)
    emp_prob = {
        "first_name": "ProbEmp",
        "email": f"prob-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": str(today),
        "probation_end_date": str(today + timedelta(days=90)),
        "level": "L1",
    }
    r_prob = client.post("/api/v1/employees", headers=hr_headers, json=emp_prob)
    assert r_prob.status_code == 201
    assert r_prob.json()["notice_period_days"] == 30

    # Explicit value wins
    emp_exp = {
        "first_name": "ExpEmp",
        "email": f"exp-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": str(today),
        "level": "L1",
        "notice_period_days": 14,
    }
    r_exp = client.post("/api/v1/employees", headers=hr_headers, json=emp_exp)
    assert r_exp.status_code == 201
    assert r_exp.json()["notice_period_days"] == 14

    # Existing L3 employee before PUT
    emp_l3_old = {
        "first_name": "OldL3",
        "email": f"old-l3-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": str(today),
        "level": "L3",
    }
    r_old = client.post("/api/v1/employees", headers=hr_headers, json=emp_l3_old)
    assert r_old.status_code == 201
    assert r_old.json()["notice_period_days"] == 30
    old_l3_id = r_old.json()["id"]

    # PUT full valid body with L3 = 90
    r_put = client.put(
        "/api/v1/companies/notice-period-defaults",
        headers=hr_headers,
        json={"L1": 30, "L2": 60, "L3": 90},
    )
    assert r_put.status_code == 200

    # New L3 employee gets 90
    emp_l3_new = {
        "first_name": "NewL3",
        "email": f"new-l3-{uuid.uuid4().hex[:6]}@example.com",
        "hire_date": str(today),
        "level": "L3",
    }
    r_new = client.post("/api/v1/employees", headers=hr_headers, json=emp_l3_new)
    assert r_new.status_code == 201
    assert r_new.json()["notice_period_days"] == 90

    # Old L3 employee is unchanged (still 30)
    r_old_check = client.get(f"/api/v1/employees/{old_l3_id}", headers=hr_headers)
    assert r_old_check.status_code == 200
    assert r_old_check.json()["notice_period_days"] == 30


def test_f07_payslip_already_paid_counts_paid_runs(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F7: A payroll run with status 'paid' for the last working month gives
    unpaid salary days 0.
    """
    from app.modules.payroll.models import PayrollItem, PayrollRun, PayrollRunStatus

    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    emp_user, emp = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"f7-paid-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp.last_working_date = today
    emp.resignation_status = ResignationStatus.approved
    db.commit()

    # Create a paid payroll run for today.month, today.year
    run = PayrollRun(
        id=uuid.uuid4(),
        company_id=cid,
        month=today.month,
        year=today.year,
        status=PayrollRunStatus.paid,
        idempotency_key=f"payrun-{uuid.uuid4().hex}",
        run_by=exit_setup["hr_user"].id,
        total_employees=1,
        total_gross=Decimal("100000.00"),
        total_net=Decimal("90000.00"),
    )
    db.add(run)
    db.flush()

    item = PayrollItem(
        id=uuid.uuid4(),
        company_id=cid,
        payroll_run_id=run.id,
        employee_id=emp.id,
        ctc_snapshot=Decimal("1200000.00"),
        gross_salary=Decimal("100000.00"),
        total_deductions=Decimal("10000.00"),
        net_salary=Decimal("90000.00"),
        employer_cost=Decimal("100000.00"),
        working_days=Decimal("30"),
        present_days=Decimal("30"),
        earnings_json=[],
        deductions_json=[],
        employer_contributions_json=[],
    )
    db.add(item)
    db.commit()

    r_fnf = client.get(f"/api/v1/employees/{emp.id}/fnf", headers=hr_headers)
    assert r_fnf.status_code == 200
    assert r_fnf.json()["unpaid_salary_days"] == 0
    assert Decimal(str(r_fnf.json()["unpaid_salary_amount"])) == Decimal("0.00")


def test_f08_typed_api_docs(client: TestClient) -> None:
    """F8: GET /{employee_id}/fnf and PUT /{employee_id}/fnf/clearance OpenAPI schema
    lists the union of 4 models.
    """
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    fnf_get = schema["paths"]["/api/v1/employees/{employee_id}/fnf"]["get"]["responses"]["200"]
    fnf_put = schema["paths"]["/api/v1/employees/{employee_id}/fnf/clearance"]["put"]["responses"][
        "200"
    ]

    # Assert schema contains references to the 4 models
    content_get = str(fnf_get)
    content_put = str(fnf_put)
    for model_name in [
        "FnFSettlementResponse",
        "FnFFinanceClearanceResponse",
        "FnFITClearanceResponse",
        "FnFHRClearanceResponse",
    ]:
        assert model_name in content_get, f"{model_name} missing from GET /fnf OpenAPI doc"
        assert model_name in content_put, (
            f"{model_name} missing from PUT /fnf/clearance OpenAPI doc"
        )


@pytest.mark.parametrize(
    "route_action,method,path_tmpl,headers_role,limit_cap",
    [
        ("submit_resignation", "POST", "/api/v1/employees/{id}/resignation", "emp", 10),
        ("withdraw_resignation", "POST", "/api/v1/employees/{id}/resignation/withdraw", "emp", 10),
        ("approve_resignation", "PUT", "/api/v1/employees/{id}/resignation/approve", "hr", 30),
        ("update_fnf_clearance", "PUT", "/api/v1/employees/{id}/fnf/clearance", "hr", 30),
        ("clearance_queue", "GET", "/api/v1/employees/clearance-queue", "hr", 30),
        ("get_fnf", "GET", "/api/v1/employees/{id}/fnf", "hr", 30),
        ("notice_defaults", "PUT", "/api/v1/companies/notice-period-defaults", "hr", 30),
    ],
)
def test_f09_rate_limiting_all_routes(
    client: TestClient,
    exit_setup: dict[str, Any],
    db: Session,
    route_action: str,
    method: str,
    path_tmpl: str,
    headers_role: str,
    limit_cap: int,
) -> None:
    """F9: With limiter enabled, exceeding rate limit gives 429."""
    limiter.enabled = True
    limiter.reset()

    cid = exit_setup["company_a"].id
    today = date.today()
    hr_headers = _auth_headers(exit_setup["hr_user"])

    try:
        user, emp = _create_user_and_employee(
            db,
            cid,
            UserRole.employee,
            email=f"rl-{route_action}-{uuid.uuid4().hex[:6]}@example.com",
        )
        emp.hire_date = today - timedelta(days=60)
        emp.resignation_status = ResignationStatus.approved
        emp.last_working_date = today
        db.commit()

        headers = _auth_headers(user) if headers_role == "emp" else hr_headers
        url = path_tmpl.replace("{id}", str(emp.id))

        payload: dict[str, Any] = {}
        if route_action == "submit_resignation":
            payload = {
                "resignation_date": str(today),
                "last_working_date": str(today),
                "reason": "RL test",
            }
        elif route_action == "approve_resignation":
            payload = {"approved": True}
        elif route_action == "update_fnf_clearance":
            payload = {"it_clearance": True}
        elif route_action == "notice_defaults":
            payload = {"L1": 30, "L2": 30, "L3": 30}

        codes: list[int] = []
        for _ in range(limit_cap + 1):
            if method == "POST":
                res = client.post(url, headers=headers, json=payload)
            elif method == "PUT":
                res = client.put(url, headers=headers, json=payload)
            else:
                res = client.get(url, headers=headers)
            codes.append(res.status_code)

        assert codes[-1] == 429, (
            f"Expected 429 on call {limit_cap + 1} for {route_action}, got codes: {codes}"
        )
    finally:
        limiter.reset()


def test_f10_reply_shapes_per_role(
    client: TestClient, exit_setup: dict[str, Any], db: Session
) -> None:
    """F10:
    - IT, HR and Finance replies: monthly_gross_salary and per_day_salary are ABSENT.
    - total_settlement_amount present only for Finance and HR-level.
    - IT reply has asset_deductions only (no other money).
    """
    hr_headers = _auth_headers(exit_setup["hr_user"])
    cid = exit_setup["company_a"].id
    today = date.today()

    emp_user, emp = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"f10-reply-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp.hire_date = today - timedelta(days=100)
    emp.is_active = True
    emp.resignation_status = ResignationStatus.approved
    emp.last_working_date = today
    db.commit()

    # Create department managers for IT, HR, Finance
    from app.modules.hr.models import Department

    it_dept = Department(
        id=uuid.uuid4(), company_id=cid, name=f"IT-{uuid.uuid4().hex[:6]}", clearance_function="it"
    )
    hr_dept = Department(
        id=uuid.uuid4(), company_id=cid, name=f"HR-{uuid.uuid4().hex[:6]}", clearance_function="hr"
    )
    fin_dept = Department(
        id=uuid.uuid4(),
        company_id=cid,
        name=f"Fin-{uuid.uuid4().hex[:6]}",
        clearance_function="finance",
    )
    db.add_all([it_dept, hr_dept, fin_dept])
    db.flush()

    it_u, it_e = _create_user_and_employee(
        db, cid, UserRole.manager, email=f"it-mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    hr_u, hr_e = _create_user_and_employee(
        db, cid, UserRole.manager, email=f"hr-mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    fin_u, fin_e = _create_user_and_employee(
        db, cid, UserRole.manager, email=f"fin-mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    it_e.department_id = it_dept.id
    hr_e.department_id = hr_dept.id
    fin_e.department_id = fin_dept.id
    db.commit()

    it_hdrs = _auth_headers(it_u)
    hr_mgr_hdrs = _auth_headers(hr_u)
    fin_hdrs = _auth_headers(fin_u)

    # 1. IT manager signs IT clearance
    r_it = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance", headers=it_hdrs, json={"it_clearance": True}
    )
    assert r_it.status_code == 200
    it_json = r_it.json()
    assert "monthly_gross_salary" not in it_json
    assert "per_day_salary" not in it_json
    assert "total_settlement_amount" not in it_json
    assert "severance_pay" not in it_json
    assert "pending_reimbursements" not in it_json
    assert "gratuity_bonus" not in it_json
    assert "asset_deductions" in it_json

    # 2. HR manager signs HR clearance
    r_hr = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=hr_mgr_hdrs,
        json={"hr_clearance": True},
    )
    assert r_hr.status_code == 200
    hr_json = r_hr.json()
    assert "monthly_gross_salary" not in hr_json
    assert "per_day_salary" not in hr_json
    assert "total_settlement_amount" not in hr_json
    assert "asset_deductions" not in hr_json
    assert "severance_pay" not in hr_json

    # 3. Finance manager signs Finance clearance
    r_fin = client.put(
        f"/api/v1/employees/{emp.id}/fnf/clearance",
        headers=fin_hdrs,
        json={"finance_clearance": True},
    )
    assert r_fin.status_code == 200
    fin_json = r_fin.json()
    assert "monthly_gross_salary" not in fin_json
    assert "per_day_salary" not in fin_json
    assert "total_settlement_amount" in fin_json
    assert "severance_pay" in fin_json
    assert "pending_reimbursements" in fin_json

    # 4. HR-level gets full response
    r_exec = client.get(f"/api/v1/employees/{emp.id}/fnf", headers=hr_headers)
    assert r_exec.status_code == 200
    exec_json = r_exec.json()
    assert "monthly_gross_salary" in exec_json
    assert "per_day_salary" in exec_json
    assert "total_settlement_amount" in exec_json


def test_f11_scope_tests(client: TestClient, exit_setup: dict[str, Any], db: Session) -> None:
    """F11:
    - Manager without a clearance function gets 403 on queue and on clearance.
    - Plain employee gets 403 on queue.
    - Queue never lists another company's employees.
    - Department-function manager sees only employees whose own function is still pending.
    """
    cid = exit_setup["company_a"].id
    today = date.today()
    hr_headers = _auth_headers(exit_setup["hr_user"])

    # 1. Plain employee gets 403 on clearance-queue
    emp_headers = _auth_headers(exit_setup["emp_user"])
    assert client.get("/api/v1/employees/clearance-queue", headers=emp_headers).status_code == 403

    # 2. Manager without clearance function gets 403 on queue and clearance update
    plain_mgr_user, plain_mgr_emp = _create_user_and_employee(
        db, cid, UserRole.manager, email=f"plain-mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    db.commit()
    plain_mgr_hdrs = _auth_headers(plain_mgr_user)

    assert (
        client.get("/api/v1/employees/clearance-queue", headers=plain_mgr_hdrs).status_code == 403
    )

    emp_test_user, emp_test = _create_user_and_employee(
        db, cid, UserRole.employee, email=f"emp-test-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_test.resignation_status = ResignationStatus.approved
    emp_test.last_working_date = today
    db.commit()

    assert (
        client.put(
            f"/api/v1/employees/{emp_test.id}/fnf/clearance",
            headers=plain_mgr_hdrs,
            json={"it_clearance": True},
        ).status_code
        == 403
    )

    # 3. Queue never lists another company's employees
    hr_b_headers = _auth_headers(exit_setup["hr_user_b"])
    r_create_b = client.post(
        "/api/v1/employees",
        headers=hr_b_headers,
        json={
            "first_name": "EmpCoB",
            "email": f"emp-b-{uuid.uuid4().hex[:6]}@example.com",
            "hire_date": str(today),
        },
    )
    assert r_create_b.status_code == 201
    emp_b_id = r_create_b.json()["id"]

    # Submit and approve resignation in Company B
    client.post(
        f"/api/v1/employees/{emp_b_id}/resignation",
        headers=hr_b_headers,
        json={
            "resignation_date": str(today),
            "last_working_date": str(today),
            "reason": "Exit Co B",
        },
    )
    client.put(
        f"/api/v1/employees/{emp_b_id}/resignation/approve",
        headers=hr_b_headers,
        json={"approved": True},
    )

    r_queue = client.get("/api/v1/employees/clearance-queue", headers=hr_headers)
    assert r_queue.status_code == 200
    q_items = r_queue.json()["items"]
    assert all(item["id"] != str(emp_b_id) for item in q_items)

    # 4. Department-function manager sees only employees whose own function is pending
    from app.modules.hr.models import Department

    it_dept = Department(
        id=uuid.uuid4(), company_id=cid, name=f"IT2-{uuid.uuid4().hex[:6]}", clearance_function="it"
    )
    db.add(it_dept)
    db.flush()

    it_u, it_e = _create_user_and_employee(
        db, cid, UserRole.manager, email=f"it-mgr2-{uuid.uuid4().hex[:6]}@example.com"
    )
    it_e.department_id = it_dept.id
    db.commit()
    it_hdrs = _auth_headers(it_u)

    # emp_test has it_clearance = False -> appears in IT queue
    r_it_q1 = client.get("/api/v1/employees/clearance-queue", headers=it_hdrs)
    assert any(item["id"] == str(emp_test.id) for item in r_it_q1.json()["items"])

    # Sign IT clearance -> it_clearance becomes True
    client.put(
        f"/api/v1/employees/{emp_test.id}/fnf/clearance",
        headers=it_hdrs,
        json={"it_clearance": True},
    )

    # emp_test now disappeared from IT manager's queue
    r_it_q2 = client.get("/api/v1/employees/clearance-queue", headers=it_hdrs)
    assert all(item["id"] != str(emp_test.id) for item in r_it_q2.json()["items"])
