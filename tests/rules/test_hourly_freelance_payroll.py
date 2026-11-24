"""Tests for Prompt C Part 3: Hourly and Freelance payroll rate resolution.

Covers:
- Per-project ProjectMemberRate wins over salary-record hourly_rate
- Effective-dated rate change mid-month splits correctly across projects and dates
- Freelancer with no rate configured at project or salary level refuses the run naming the employee
- Contract employee with no rate uses the (CTC / 12) / 160 fallback and is labeled
- Totals are Decimal with ROUND_HALF_UP throughout
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.db.rls import bind_tenant_to_session
from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.hr.models import Department, Employee, EmploymentType
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole
from app.modules.payroll.models import (
    EmployeeSalary,
    PayrollItem,
    SalaryComponent,
    SalaryStructure,
    StatutoryConfig,
)
from app.modules.payroll.schemas import PayrollRunCreateRequest
from app.modules.payroll.service import PayrollRunService
from app.modules.projects.models import Project, ProjectMemberRate, TimeEntry

TEST_PASSWORD_HASH = hash_password("TestPass1234!")


@pytest.fixture
def hourly_payroll_env(db: Session):
    seed_statutory_rates(db)
    seed_pt_slabs(db)
    seed_tax_slabs(db)

    cid = uuid.uuid4()
    code = f"H{uuid.uuid4().hex[:4].upper()}"
    company = Company(
        id=cid,
        name="Hourly Test Corp",
        code=code,
        email=f"{code.lower()}@example.com",
        status=CompanyStatus.active,
        country="IN",
    )
    db.add(company)
    db.flush()

    bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

    settings = CompanySettings(
        company_id=cid,
        payroll_working_days_basis="calendar_days",
    )
    db.add(settings)

    hr_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=TEST_PASSWORD_HASH,
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr_user)

    dept = Department(id=uuid.uuid4(), company_id=cid, name="Engineering")
    db.add(dept)

    # Standard salary structure
    struct = SalaryStructure(
        id=uuid.uuid4(),
        company_id=cid,
        name="Contractor Structure",
        is_active=True,
    )
    db.add(struct)
    db.flush()

    comp = SalaryComponent(
        id=uuid.uuid4(),
        company_id=cid,
        structure_id=struct.id,
        name="Basic Salary",
        code="BASIC",
        type="earning",
        calculation_type="fixed",
        value=Decimal("0.00"),
        is_taxable=True,
        is_statutory=False,
        display_order=1,
    )
    db.add(comp)

    # Statutory config
    stat = StatutoryConfig(
        company_id=cid,
        country="IN",
        pt_state="Gujarat",
    )
    db.add(stat)
    db.flush()

    return {
        "company_id": cid,
        "hr_user": hr_user,
        "dept": dept,
        "structure": struct,
    }


def _create_employee(
    db: Session,
    company_id: uuid.UUID,
    first_name: str,
    last_name: str,
    emp_code: str,
    emp_type: EmploymentType,
    structure_id: uuid.UUID,
    ctc: Decimal = Decimal("600000.00"),
    hourly_rate: Decimal | None = None,
) -> Employee:
    user = User(
        id=uuid.uuid4(),
        company_id=company_id,
        email=f"{emp_code.lower()}@example.com",
        hashed_password=TEST_PASSWORD_HASH,
        role=UserRole.employee,
        is_active=True,
    )
    db.add(user)
    db.flush()

    emp = Employee(
        id=uuid.uuid4(),
        company_id=company_id,
        user_id=user.id,
        employee_code=emp_code,
        first_name=first_name,
        last_name=last_name,
        email=user.email,
        employment_type=emp_type,
        hire_date=date(2025, 1, 1),
    )
    db.add(emp)
    db.flush()

    sal = EmployeeSalary(
        company_id=company_id,
        employee_id=emp.id,
        structure_id=structure_id,
        ctc=ctc,
        hourly_rate=hourly_rate,
        effective_from=date(2025, 1, 1),
        created_by=user.id,
    )
    db.add(sal)
    db.flush()
    return emp


def _create_project(db: Session, company_id: uuid.UUID, name: str, code: str) -> Project:
    proj = Project(
        id=uuid.uuid4(),
        company_id=company_id,
        name=name,
        code=code,
        status="active",
    )
    db.add(proj)
    db.flush()
    return proj


def test_part3_project_member_rate_wins_over_salary_rate(db: Session, hourly_payroll_env):
    """Part 3: ProjectMemberRate wins over salary_record.hourly_rate."""
    cid = hourly_payroll_env["company_id"]
    struct = hourly_payroll_env["structure"]

    emp = _create_employee(
        db,
        cid,
        "Alice",
        "Contractor",
        "CON-001",
        EmploymentType.contract,
        struct.id,
        hourly_rate=Decimal("500.00"),
    )
    proj = _create_project(db, cid, "Alpha Project", "PRJ-A")

    # Add ProjectMemberRate of 750.00 effective from 2025-04-01
    rate_record = ProjectMemberRate(
        company_id=cid,
        project_id=proj.id,
        employee_id=emp.id,
        rate=Decimal("750.00"),
        effective_from=date(2025, 4, 1),
    )
    db.add(rate_record)

    # 10 approved hours on Alpha Project
    te = TimeEntry(
        company_id=cid,
        project_id=proj.id,
        employee_id=emp.id,
        date=date(2025, 5, 15),
        hours=Decimal("10.00"),
        status="approved",
    )
    db.add(te)
    db.commit()

    service = PayrollRunService(db)
    run = service.create_run(
        cid,
        PayrollRunCreateRequest(month=5, year=2025, run_type="regular"),
        str(uuid.uuid4()),
        hourly_payroll_env["hr_user"],
    )

    item = (
        db.query(PayrollItem)
        .filter(PayrollItem.payroll_run_id == run.id, PayrollItem.employee_id == emp.id)
        .one()
    )
    # 10 hrs * 750 = 7500.00, NOT 5000.00
    assert item.gross_salary == Decimal("7500.00")
    proj_lines = [e for e in item.earnings_json if e.get("code") == "PROJECT_HOURS"]
    assert len(proj_lines) == 1
    assert proj_lines[0]["rate"] == "750.00"
    assert proj_lines[0]["hours"] == "10.00"
    assert proj_lines[0]["amount"] == "7500.00"
    assert not proj_lines[0]["is_fallback"]


def test_part3_effective_dated_rate_change_mid_month_splits_correctly(
    db: Session, hourly_payroll_env
):
    """Part 3: Mid-month rate change splits correctly across dates."""
    cid = hourly_payroll_env["company_id"]
    struct = hourly_payroll_env["structure"]

    emp = _create_employee(
        db,
        cid,
        "Bob",
        "Freelancer",
        "FREE-001",
        EmploymentType.freelancer,
        struct.id,
    )
    proj = _create_project(db, cid, "Beta Project", "PRJ-B")

    # Rate 600 from May 1, rate 800 from May 16
    db.add(
        ProjectMemberRate(
            company_id=cid,
            project_id=proj.id,
            employee_id=emp.id,
            rate=Decimal("600.00"),
            effective_from=date(2025, 5, 1),
        )
    )
    db.add(
        ProjectMemberRate(
            company_id=cid,
            project_id=proj.id,
            employee_id=emp.id,
            rate=Decimal("800.00"),
            effective_from=date(2025, 5, 16),
        )
    )

    # Time entries: 8 hrs on May 10 (@600), 12 hrs on May 20 (@800)
    db.add(
        TimeEntry(
            company_id=cid,
            project_id=proj.id,
            employee_id=emp.id,
            date=date(2025, 5, 10),
            hours=Decimal("8.00"),
            status="approved",
        )
    )
    db.add(
        TimeEntry(
            company_id=cid,
            project_id=proj.id,
            employee_id=emp.id,
            date=date(2025, 5, 20),
            hours=Decimal("12.00"),
            status="approved",
        )
    )
    db.commit()

    service = PayrollRunService(db)
    run = service.create_run(
        cid,
        PayrollRunCreateRequest(month=5, year=2025, run_type="regular"),
        str(uuid.uuid4()),
        hourly_payroll_env["hr_user"],
    )

    item = (
        db.query(PayrollItem)
        .filter(PayrollItem.payroll_run_id == run.id, PayrollItem.employee_id == emp.id)
        .one()
    )
    # 8*600 = 4800, 12*800 = 9600; Total = 14400.00
    assert item.gross_salary == Decimal("14400.00")
    proj_lines = sorted(
        [e for e in item.earnings_json if e.get("code") == "PROJECT_HOURS"],
        key=lambda x: Decimal(x["rate"]),
    )
    assert len(proj_lines) == 2
    assert proj_lines[0]["rate"] == "600.00"
    assert proj_lines[0]["hours"] == "8.00"
    assert proj_lines[0]["amount"] == "4800.00"
    assert proj_lines[1]["rate"] == "800.00"
    assert proj_lines[1]["hours"] == "12.00"
    assert proj_lines[1]["amount"] == "9600.00"


def test_part3_freelancer_with_no_rate_refuses_run_naming_employee(db: Session, hourly_payroll_env):
    """Part 3: Freelancer with no rate at project or salary level refuses the run."""
    cid = hourly_payroll_env["company_id"]
    struct = hourly_payroll_env["structure"]

    emp = _create_employee(
        db,
        cid,
        "Charlie",
        "Writer",
        "FREE-999",
        EmploymentType.freelancer,
        struct.id,
        hourly_rate=None,
    )
    proj = _create_project(db, cid, "Gamma Project", "PRJ-G")

    # Time entry with no ProjectMemberRate and no salary hourly_rate
    db.add(
        TimeEntry(
            company_id=cid,
            project_id=proj.id,
            employee_id=emp.id,
            date=date(2025, 5, 10),
            hours=Decimal("15.00"),
            status="approved",
        )
    )
    db.commit()

    service = PayrollRunService(db)
    with pytest.raises(ConflictError) as exc_info:
        service.create_run(
            cid,
            PayrollRunCreateRequest(month=5, year=2025, run_type="regular"),
            str(uuid.uuid4()),
            hourly_payroll_env["hr_user"],
        )

    err_msg = str(exc_info.value)
    assert "Payroll run cannot be processed" in err_msg
    assert "Freelancer 'Charlie Writer'" in err_msg
    assert "FREE-999" in err_msg
    assert "no hourly rate configured" in err_msg


def test_part3_contract_employee_with_no_rate_uses_fallback_and_is_labeled(
    db: Session, hourly_payroll_env
):
    """Part 3: Contract employee with no rate uses (CTC / 12) / 160 fallback and is labeled."""
    cid = hourly_payroll_env["company_id"]
    struct = hourly_payroll_env["structure"]

    # CTC 600,000 -> Monthly 50,000 -> Hourly 50000 / 160 = 312.50
    emp = _create_employee(
        db,
        cid,
        "Dana",
        "Tester",
        "CON-555",
        EmploymentType.contract,
        struct.id,
        ctc=Decimal("600000.00"),
        hourly_rate=None,
    )
    proj = _create_project(db, cid, "Delta Project", "PRJ-D")

    db.add(
        TimeEntry(
            company_id=cid,
            project_id=proj.id,
            employee_id=emp.id,
            date=date(2025, 5, 5),
            hours=Decimal("20.00"),
            status="approved",
        )
    )
    db.commit()

    service = PayrollRunService(db)
    run = service.create_run(
        cid,
        PayrollRunCreateRequest(month=5, year=2025, run_type="regular"),
        str(uuid.uuid4()),
        hourly_payroll_env["hr_user"],
    )

    item = (
        db.query(PayrollItem)
        .filter(PayrollItem.payroll_run_id == run.id, PayrollItem.employee_id == emp.id)
        .one()
    )
    # 20 * 312.50 = 6250.00
    assert item.gross_salary == Decimal("6250.00")
    proj_lines = [e for e in item.earnings_json if e.get("code") == "PROJECT_HOURS"]
    assert len(proj_lines) == 1
    assert proj_lines[0]["rate"] == "312.50"
    assert proj_lines[0]["hours"] == "20.00"
    assert proj_lines[0]["amount"] == "6250.00"
    assert proj_lines[0]["is_fallback"] is True
    assert "[Fallback Rate Used]" in proj_lines[0]["name"]
