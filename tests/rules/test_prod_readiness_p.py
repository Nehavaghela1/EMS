"""Tests for PART P: Attendance cannot change after payroll is paid.

P1: Established baseline (reported in final report).
P2: Once a payroll run covering a date is in a paid state, writing attendance
    for that date is refused with 409 and a message naming the run and period.
    Same for approving a regularization that would change a locked day.
P3: HR explicit unlock on the run (hr_admin or owner only), audited, reason 1-500 chars.
    Explicit relock supported and audited.
P4: Tests:
    - writing attendance inside a paid period returns 409;
    - outside it succeeds;
    - approving a regularization inside a paid period returns 409;
    - after an audited unlock the write succeeds;
    - an employee or manager cannot unlock;
    - another tenant's run_id returns 404;
    - paid off-cycle or bonus run does NOT lock regular attendance;
    - relocking the run locks attendance again.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.time import utcnow
from app.modules.hr.models import Employee, EmploymentType
from app.modules.identity.models import User, UserRole
from app.modules.payroll.models import (
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
)
from app.modules.platform.models import AuditLog
from app.modules.time_leave.models import (
    Attendance,
    AttendanceRegularizationRequest,
    AttendanceSource,
    AttendanceStatus,
    RegularizationStatus,
)
from tests.conftest import TenantContext


def _create_user_and_employee(
    db: Session,
    company_id: uuid.UUID,
    role: UserRole,
    email: str | None = None,
) -> tuple[User, Employee]:
    from app.db.rls import bind_tenant_to_session

    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=False)
    email = email or f"user-{uuid.uuid4().hex[:6]}@example.com"
    user = User(
        id=uuid.uuid4(),
        company_id=company_id,
        email=email,
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    emp = Employee(
        id=uuid.uuid4(),
        company_id=company_id,
        user_id=user.id,
        employee_code=f"EMP-{uuid.uuid4().hex[:5]}",
        first_name="Test",
        last_name="User",
        email=email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2025, 1, 1),
        notice_period_days=30,
        is_active=True,
    )
    db.add(emp)
    db.commit()
    return user, emp


def _create_paid_run(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    month: int,
    year: int,
    run_type: PayrollRunType = PayrollRunType.regular,
    is_unlocked: bool = False,
) -> PayrollRun:
    run = PayrollRun(
        id=uuid.uuid4(),
        company_id=company_id,
        month=month,
        year=year,
        status=PayrollRunStatus.paid,
        run_type=run_type,
        idempotency_key=f"run-{uuid.uuid4().hex}",
        run_by=user_id,
        approved_by=user_id,
        approved_at=utcnow(),
        is_attendance_unlocked=is_unlocked,
    )
    db.add(run)
    db.commit()
    return run


def test_p2_attendance_write_inside_paid_period_returns_409(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    # Target date: last month (e.g., 2026-10-15)
    past_date = date(2026, 10, 15)
    user, emp = _create_user_and_employee(db, company_a.company_id, UserRole.employee)

    # Existing attendance record on past_date
    att = Attendance(
        id=uuid.uuid4(),
        company_id=company_a.company_id,
        employee_id=emp.id,
        date=past_date,
        status=AttendanceStatus.present,
        source=AttendanceSource.web,
        check_in=datetime(2026, 10, 15, 9, 0, tzinfo=UTC),
        check_out=datetime(2026, 10, 15, 17, 0, tzinfo=UTC),
        hours_worked=Decimal("8.00"),
    )
    db.add(att)
    db.commit()

    # Create paid regular payroll run for that month
    run = _create_paid_run(
        db, company_a.company_id, user.id, month=10, year=2026, run_type=PayrollRunType.regular
    )

    # HR attempts direct regularize/correction on that attendance
    res = client.put(
        f"/api/v1/attendance/{att.id}",
        json={
            "check_in": "2026-10-15T09:30:00Z",
            "check_out": "2026-10-15T18:00:00Z",
            "reason": "Correcting hours",
        },
        headers=company_a.hr_headers,
    )
    assert res.status_code == 409
    err_msg = res.json()["error"]["message"]
    assert str(run.id) in err_msg
    assert "10/2026" in err_msg


def test_p2_attendance_write_outside_paid_period_succeeds(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    # Target date: 2026-09-15 (September is NOT paid)
    sept_date = date(2026, 9, 15)
    user, emp = _create_user_and_employee(db, company_a.company_id, UserRole.employee)

    att = Attendance(
        id=uuid.uuid4(),
        company_id=company_a.company_id,
        employee_id=emp.id,
        date=sept_date,
        status=AttendanceStatus.present,
        source=AttendanceSource.web,
        check_in=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
        check_out=datetime(2026, 9, 15, 17, 0, tzinfo=UTC),
        hours_worked=Decimal("8.00"),
    )
    db.add(att)
    db.commit()

    # Paid run is for October 2026, not September
    _create_paid_run(
        db, company_a.company_id, user.id, month=10, year=2026, run_type=PayrollRunType.regular
    )

    res = client.put(
        f"/api/v1/attendance/{att.id}",
        json={
            "check_in": "2026-09-15T09:30:00Z",
            "check_out": "2026-09-15T18:00:00Z",
            "reason": "September correction",
        },
        headers=company_a.hr_headers,
    )
    assert res.status_code == 200


def test_p2_approving_regularization_inside_paid_period_returns_409(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    past_date = date(2026, 10, 20)
    user, emp = _create_user_and_employee(db, company_a.company_id, UserRole.employee)

    att = Attendance(
        id=uuid.uuid4(),
        company_id=company_a.company_id,
        employee_id=emp.id,
        date=past_date,
        status=AttendanceStatus.mispunch,
        source=AttendanceSource.web,
        check_in=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    )
    db.add(att)
    db.flush()

    reg = AttendanceRegularizationRequest(
        id=uuid.uuid4(),
        company_id=company_a.company_id,
        attendance_id=att.id,
        employee_id=emp.id,
        requested_check_in=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        requested_check_out=datetime(2026, 10, 20, 18, 0, tzinfo=UTC),
        reason="Forgot checkout",
        status=RegularizationStatus.pending,
    )
    db.add(reg)
    db.commit()

    run = _create_paid_run(
        db, company_a.company_id, user.id, month=10, year=2026, run_type=PayrollRunType.regular
    )

    # HR approves regularization
    res = client.put(
        f"/api/v1/attendance/regularizations/{reg.id}/approve",
        json={"status": "approved"},
        headers=company_a.hr_headers,
    )
    assert res.status_code == 409
    err_msg = res.json()["error"]["message"]
    assert str(run.id) in err_msg
    assert "10/2026" in err_msg


def test_p3_audited_unlock_allows_write_and_relock_refuses_it(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    past_date = date(2026, 8, 10)
    user, emp = _create_user_and_employee(db, company_a.company_id, UserRole.employee)

    att = Attendance(
        id=uuid.uuid4(),
        company_id=company_a.company_id,
        employee_id=emp.id,
        date=past_date,
        status=AttendanceStatus.present,
        source=AttendanceSource.web,
        check_in=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        check_out=datetime(2026, 8, 10, 17, 0, tzinfo=UTC),
        hours_worked=Decimal("8.00"),
    )
    db.add(att)
    db.commit()

    run = _create_paid_run(
        db, company_a.company_id, user.id, month=8, year=2026, run_type=PayrollRunType.regular
    )

    # Verify locked first
    res = client.put(
        f"/api/v1/attendance/{att.id}",
        json={"check_in": "2026-08-10T09:15:00Z", "reason": "Attempt before unlock"},
        headers=company_a.hr_headers,
    )
    assert res.status_code == 409

    # Unlock requires valid reason of 1-500 chars
    res_bad_unlock = client.post(
        f"/api/v1/payroll/runs/{run.id}/unlock-attendance",
        json={"unlocked": True, "reason": "   "},
        headers=company_a.hr_headers,
    )
    assert res_bad_unlock.status_code in (422, 400)

    # Valid unlock
    unlock_reason = "HR audit ticket #8942: punch clock correction"
    res_unlock = client.post(
        f"/api/v1/payroll/runs/{run.id}/unlock-attendance",
        json={"unlocked": True, "reason": unlock_reason},
        headers=company_a.hr_headers,
    )
    assert res_unlock.status_code == 200
    assert res_unlock.json()["is_attendance_unlocked"] is True

    # Audit row exists for unlock
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "PAYROLL_RUN_ATTENDANCE_UNLOCKED",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["reason"] == unlock_reason

    # Now write succeeds
    res_write = client.put(
        f"/api/v1/attendance/{att.id}",
        json={"check_in": "2026-08-10T09:15:00Z", "reason": "HR correction after unlock"},
        headers=company_a.hr_headers,
    )
    assert res_write.status_code == 200

    # Explicit re-lock sets is_attendance_unlocked = False and is audited
    relock_reason = "Audit correction completed, sealing attendance again"
    res_relock = client.post(
        f"/api/v1/payroll/runs/{run.id}/lock-attendance",
        json={"unlocked": False, "reason": relock_reason},
        headers=company_a.hr_headers,
    )
    assert res_relock.status_code == 200
    assert res_relock.json()["is_attendance_unlocked"] is False

    relock_audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "PAYROLL_RUN_ATTENDANCE_RELOCKED",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert relock_audit is not None
    assert relock_audit.details["reason"] == relock_reason

    # Writing is locked again (409)
    res_relocked_write = client.put(
        f"/api/v1/attendance/{att.id}",
        json={"check_in": "2026-08-10T09:20:00Z", "reason": "Attempt after relock"},
        headers=company_a.hr_headers,
    )
    assert res_relocked_write.status_code == 409


def test_p4_roles_and_cross_tenant(
    client: TestClient, company_a: TenantContext, company_b: TenantContext, db: Session
) -> None:
    user, _emp = _create_user_and_employee(db, company_a.company_id, UserRole.employee)
    run = _create_paid_run(
        db, company_a.company_id, user.id, month=7, year=2026, run_type=PayrollRunType.regular
    )

    # Employee cannot unlock -> 403
    res_emp = client.post(
        f"/api/v1/payroll/runs/{run.id}/unlock-attendance",
        json={"unlocked": True, "reason": "Employee attempt"},
        headers=company_a.employee_headers,
    )
    assert res_emp.status_code == 403

    # Manager cannot unlock -> 403
    res_mgr = client.post(
        f"/api/v1/payroll/runs/{run.id}/unlock-attendance",
        json={"unlocked": True, "reason": "Manager attempt"},
        headers=company_a.manager_headers,
    )
    assert res_mgr.status_code == 403

    # Another tenant's run_id returns 404, never 403
    res_other_tenant = client.post(
        f"/api/v1/payroll/runs/{run.id}/unlock-attendance",
        json={"unlocked": True, "reason": "Tenant B attempt"},
        headers=company_b.hr_headers,
    )
    assert res_other_tenant.status_code == 404


def test_p4_off_cycle_run_does_not_lock_attendance(
    client: TestClient, company_a: TenantContext, db: Session
) -> None:
    # Decision: Only paid regular runs lock attendance; off-cycle or bonus runs do not lock it.
    june_date = date(2026, 6, 12)
    user, emp = _create_user_and_employee(db, company_a.company_id, UserRole.employee)

    att = Attendance(
        id=uuid.uuid4(),
        company_id=company_a.company_id,
        employee_id=emp.id,
        date=june_date,
        status=AttendanceStatus.present,
        source=AttendanceSource.web,
        check_in=datetime(2026, 6, 12, 9, 0, tzinfo=UTC),
        check_out=datetime(2026, 6, 12, 17, 0, tzinfo=UTC),
        hours_worked=Decimal("8.00"),
    )
    db.add(att)
    db.commit()

    # Off-cycle paid run for June 2026
    _create_paid_run(
        db, company_a.company_id, user.id, month=6, year=2026, run_type=PayrollRunType.off_cycle
    )

    # Writing attendance for June succeeds because there is no regular paid run
    res = client.put(
        f"/api/v1/attendance/{att.id}",
        json={"check_in": "2026-06-12T09:30:00Z", "reason": "Off-cycle doesn't lock"},
        headers=company_a.hr_headers,
    )
    assert res.status_code == 200
