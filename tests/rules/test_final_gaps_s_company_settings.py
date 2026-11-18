"""Part S tests: Honour company working-days basis and full-day-hours settings.

Tests:
1. Three companies, one per basis (calendar_days, working_days, fixed_30), same employee, same salary,
   same single-day absence in the same month, asserting three different deduction amounts exact to the paisa.
2. Company with no settings row behaves as calendar_days.
3. S2: project hourly cost = that month's working days from S1 x company's full_day_hours, with 22 x 8 = 176 fallback.
"""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType
from app.modules.identity.models import (
    Company,
    CompanySettings,
    CompanyStatus,
    PayrollWorkingDaysBasis,
    User,
    UserRole,
)
from app.modules.payroll.models import (
    CalculationType,
    EmployeeSalary,
    PayrollRun,
    PayrollRunStatus,
    SalaryComponent,
    SalaryComponentType,
    SalaryStructure,
    StatutoryConfig,
)
from app.modules.payroll.schemas import PayrollRunCreateRequest
from app.modules.payroll.service import PayrollRunService
from app.modules.projects.service import ProjectService
from app.modules.time_leave.models import Attendance, AttendanceSource, AttendanceStatus


def _setup_company_with_basis(
    db: Session,
    basis: PayrollWorkingDaysBasis | None,
    full_day_hours: Decimal = Decimal("8.00"),
) -> tuple[Company, User, Employee, SalaryStructure]:
    cid = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    code = f"C{uuid.uuid4().hex[:4].upper()}"
    company = Company(
        id=cid,
        name=f"Test_{code}",
        code=code,
        email=f"c_{code.lower()}@test.com",
        country="IN",
        status=CompanyStatus.active,
    )
    db.add(company)
    db.flush()

    if basis is not None:
        settings = CompanySettings(
            company_id=cid,
            payroll_working_days_basis=basis,
            full_day_hours=full_day_hours,
            weekend_days=[6, 7],
        )
        db.add(settings)

    db.add(StatutoryConfig(company_id=cid, country="IN", pt_state="Gujarat"))
    db.flush()

    hr_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr_{code.lower()}@test.com",
        role=UserRole.hr_admin,
        hashed_password="pw",
        is_active=True,
    )
    db.add(hr_user)
    db.flush()

    emp_id = uuid.uuid4()
    emp = Employee(
        id=emp_id,
        company_id=cid,
        user_id=None,
        employee_code=f"E{code}",
        first_name="Alice",
        last_name="Test",
        email=f"alice_{code.lower()}@test.com",
        hire_date=date(2026, 1, 1),
        employment_type=EmploymentType.full_time,
        is_active=True,
    )
    db.add(emp)
    db.flush()

    # Salary structure: Basic only for simple math (100% of CTC)
    # CTC: 600,000 / year -> 50,000 / month gross
    struct_id = uuid.uuid4()
    struct = SalaryStructure(
        id=struct_id,
        company_id=cid,
        name="BasicOnly",
        country="IN",
        is_active=True,
    )
    db.add(struct)
    comp = SalaryComponent(
        id=uuid.uuid4(),
        company_id=cid,
        structure_id=struct_id,
        name="Basic",
        code="BASIC",
        type=SalaryComponentType.earning,
        calculation_type=CalculationType.fixed,
        value=Decimal("50000.00"),
        display_order=1,
    )
    db.add(comp)
    db.flush()

    sal = EmployeeSalary(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp_id,
        structure_id=struct_id,
        ctc=Decimal("600000.00"),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        created_by=hr_user.id,
    )
    db.add(sal)
    db.commit()

    return company, hr_user, emp, struct


def test_S1_three_companies_three_bases_and_no_settings_fallback(db: Session):
    """Month: October 2026 (31 calendar days, 22 working days Mon-Fri).
    Monthly gross: 50,000.00.
    1 absence day on a working day (Oct 5, 2026 is a Monday).
    1. calendar_days:
       daily_rate = 50,000 / 31 = 1612.9032258...
       deduction = 1 * (50000 / 31) -> earned gross = 50000 - 1612.90 = 48387.10
       Specifically: 30 / 31 * 50000 = 48387.0967... -> rounds to 48387.10
    2. working_days:
       daily_rate = 50,000 / 22 = 2272.72727...
       earned gross = 21 / 22 * 50000 = 47727.2727... -> rounds to 47727.27
    3. fixed_30:
       daily_rate = 50,000 / 30 = 1666.66666...
       earned gross = 29 / 30 * 50000 = 48333.3333... -> rounds to 48333.33
    4. no settings row:
       behaves exactly as calendar_days -> earned gross = 48387.10
    """
    y, m = 2026, 10
    absent_day = date(2026, 10, 5)  # Monday

    # 1. calendar_days
    c_cal, u_cal, emp_cal, _ = _setup_company_with_basis(db, PayrollWorkingDaysBasis.calendar_days)
    # 2. working_days
    c_wrk, u_wrk, emp_wrk, _ = _setup_company_with_basis(db, PayrollWorkingDaysBasis.working_days)
    # 3. fixed_30
    c_f30, u_f30, emp_f30, _ = _setup_company_with_basis(db, PayrollWorkingDaysBasis.fixed_30)
    # 4. no settings row
    c_none, u_none, emp_none, _ = _setup_company_with_basis(db, None)

    service = PayrollRunService(db)

    # For each, fill attendance for every day in Oct except Oct 5 (absent)
    for comp, emp in [
        (c_cal, emp_cal),
        (c_wrk, emp_wrk),
        (c_f30, emp_f30),
        (c_none, emp_none),
    ]:
        bind_tenant_to_session(db, company_id=comp.id, is_platform_admin=True)
        _, days_in_month = monthrange(y, m)
        for d in range(1, days_in_month + 1):
            day_d = date(y, m, d)
            st = AttendanceStatus.absent if day_d == absent_day else AttendanceStatus.present
            db.add(
                Attendance(
                    company_id=comp.id,
                    employee_id=emp.id,
                    date=day_d,
                    status=st,
                    source=AttendanceSource.web,
                )
            )
        db.commit()

    # Run payroll for calendar_days
    run_cal = service.create_run(
        c_cal.id,
        PayrollRunCreateRequest(month=m, year=y, run_type="regular"),
        idempotency_key=f"k-{uuid.uuid4()}",
        actor=u_cal,
    )
    item_cal = service.item_repo.list_by_run_id(run_cal.id, c_cal.id)[0]
    assert item_cal.working_days == Decimal("31.0")
    assert item_cal.gross_salary == Decimal("48387.10")

    # Run payroll for working_days
    run_wrk = service.create_run(
        c_wrk.id,
        PayrollRunCreateRequest(month=m, year=y, run_type="regular"),
        idempotency_key=f"k-{uuid.uuid4()}",
        actor=u_wrk,
    )
    item_wrk = service.item_repo.list_by_run_id(run_wrk.id, c_wrk.id)[0]
    assert item_wrk.working_days == Decimal("22.0")
    assert item_wrk.gross_salary == Decimal("47727.27")

    # Run payroll for fixed_30
    run_f30 = service.create_run(
        c_f30.id,
        PayrollRunCreateRequest(month=m, year=y, run_type="regular"),
        idempotency_key=f"k-{uuid.uuid4()}",
        actor=u_f30,
    )
    item_f30 = service.item_repo.list_by_run_id(run_f30.id, c_f30.id)[0]
    assert item_f30.working_days == Decimal("30.0")
    assert item_f30.gross_salary == Decimal("48333.33")

    # Run payroll for no settings row (fallback to calendar_days)
    run_none = service.create_run(
        c_none.id,
        PayrollRunCreateRequest(month=m, year=y, run_type="regular"),
        idempotency_key=f"k-{uuid.uuid4()}",
        actor=u_none,
    )
    item_none = service.item_repo.list_by_run_id(run_none.id, c_none.id)[0]
    assert item_none.working_days == Decimal("31.0")
    assert item_none.gross_salary == Decimal("48387.10")


def test_S2_project_standard_monthly_hours(db: Session):
    # Company with 7.50 full day hours
    c, u, emp, _ = _setup_company_with_basis(
        db, PayrollWorkingDaysBasis.working_days, full_day_hours=Decimal("7.50")
    )
    service = ProjectService(db)

    # April 2026: 22 Mon-Fri working days. 22 * 7.50 = 165.00
    hours = service.get_standard_monthly_hours(c.id, date(2026, 4, 1))
    assert hours == Decimal("165.00")

    # Company with no settings row -> fallback 176.00
    c_none, _, _, _ = _setup_company_with_basis(db, None)
    hours_fallback = service.get_standard_monthly_hours(c_none.id, date(2026, 4, 1))
    assert hours_fallback == Decimal("176.00")
