"""scripts/seed_demo.py — populates one realistic, obviously-fake demo
company so a reviewer opening the UI sees real numbers, not "No records
found." Everything below is created through the real service layer
(EmployeeService, LeaveService, ShiftService, ...) wherever that layer
doesn't require "today" as the date, so this exercises the same business
rules — employee_code generation, leave-day counting, balance math — a
real user's actions would.

Requires:
  - scripts/setup.sh already run (industry_presets seeded, migrations applied)
  - pip install -e ".[demo]"   (installs Faker — never a dependency of the
    app itself, and never installed by the ordinary `pip install -e ".[dev]"`
    setup)

Run:
    python scripts/seed_demo.py

Never invoked by scripts/setup.sh or CI — an explicit, separate choice
every time, per WP-15's own instruction. Safely re-runnable: if a company
named DEMO_COMPANY_NAME already exists, it (and everything under it) is
deleted first, then rebuilt from scratch — simpler to reason about than
true row-by-row idempotency for data this interconnected, and just as safe
to run twice.
"""

import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

try:
    from faker import Faker
except ImportError:
    print(
        "seed_demo.py: the 'faker' package is not installed. Run:\n"
        '    pip install -e ".[demo]"\n'
        "first (this is a demo-only dependency, never installed by the ordinary setup).",
        file=sys.stderr,
    )
    sys.exit(1)

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Department, Employee, EmploymentType
from app.modules.hr.repository import EmployeeRepository
from app.modules.hr.schemas import EmployeeCreateRequest
from app.modules.hr.service import EmployeeService
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole
from app.modules.identity.schemas import CompanyRegisterRequest
from app.modules.identity.service import CompanyService
from app.modules.platform.models import AuditLog, Notification
from app.modules.time_leave.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    EmployeeShift,
    Holiday,
    Leave,
    LeaveBalance,
    LeaveType,
    Shift,
)
from app.modules.time_leave.repository import AttendanceRepository
from app.modules.time_leave.schemas import (
    AttendanceRegularizeRequest,
    HolidayCreateRequest,
    LeaveApplyRequest,
    LeaveDecisionRequest,
    ShiftAssignRequest,
    ShiftCreateRequest,
)
from app.modules.time_leave.service import (
    AttendanceService,
    HolidayService,
    LeaveService,
    ShiftService,
)

DEMO_COMPANY_NAME = "Bluepeak Demo Technologies"
DEMO_COMPANY_EMAIL = "admin@bluepeak-demo.example"
DEMO_PASSWORD = "DemoPass123!"  # fixed and printed below — obviously not a real secret

SEED_ADMIN_COMPANY_NAME = "EMS Seed Admin (internal)"
SEED_ADMIN_EMAIL = "seed-admin@ems-pro.internal"

LEVELS = ["L1", "L2", "L3", "L4", "L5"]
EMPLOYMENT_TYPES = [EmploymentType.full_time] * 8 + [EmploymentType.contract, EmploymentType.intern]

fake = Faker()
Faker.seed(20260902)
random.seed(20260902)


def _wipe_existing_demo_company(app_db: Session) -> None:
    """Runs as ems_owner, not ems_app (settings.ALEMBIC_DATABASE_URL, its
    own short-lived engine) — audit_logs grants ems_app SELECT/INSERT only
    (Spec 7.8's append-only enforcement, WP-11); no amount of "this is my
    own demo data" makes DELETE possible for the app role, by design, and
    that's the correct behavior even here. ems_owner owns the table and can.
    Every other table is RLS-FORCEd even for the owner (Spec 8.3), so this
    still binds is_platform_admin=True first, exactly like the app-role
    session would.
    """
    existing = app_db.scalar(select(Company).where(Company.name == DEMO_COMPANY_NAME))
    if existing is None:
        return
    print(f"Existing demo company found ({existing.id}) — removing it first...")
    company_id = existing.id

    owner_engine = create_engine(settings.ALEMBIC_DATABASE_URL)
    try:
        with sessionmaker(bind=owner_engine)() as db:
            bind_tenant_to_session(db, company_id=company_id, is_platform_admin=True)

            db.execute(delete(Notification).where(Notification.company_id == company_id))
            db.execute(delete(AuditLog).where(AuditLog.company_id == company_id))
            db.execute(delete(EmployeeShift).where(EmployeeShift.company_id == company_id))
            db.execute(delete(Shift).where(Shift.company_id == company_id))
            db.execute(delete(LeaveBalance).where(LeaveBalance.company_id == company_id))
            db.execute(delete(Leave).where(Leave.company_id == company_id))
            db.execute(delete(LeaveType).where(LeaveType.company_id == company_id))
            db.execute(delete(Attendance).where(Attendance.company_id == company_id))
            db.execute(delete(Holiday).where(Holiday.company_id == company_id))
            # Break the two self-/mutually-referential FK cycles before deleting.
            db.query(Employee).filter(Employee.company_id == company_id).update(
                {"reporting_manager_id": None}
            )
            db.query(Department).filter(Department.company_id == company_id).update(
                {"head_employee_id": None}
            )
            db.execute(delete(Employee).where(Employee.company_id == company_id))
            db.execute(delete(Department).where(Department.company_id == company_id))
            db.execute(delete(CompanySettings).where(CompanySettings.company_id == company_id))
            db.query(Company).filter(Company.id == company_id).update({"approved_by": None})
            db.execute(delete(User).where(User.company_id == company_id))
            db.execute(delete(Company).where(Company.id == company_id))
            db.commit()
    finally:
        owner_engine.dispose()
    print("    removed.")


def _get_or_create_seed_admin(db: Session) -> User:
    """A throwaway super_admin used only to call approve_company (Spec 8.5:
    assigned only by direct database action, never a route — this script
    IS that direct database action). Reused across runs, not recreated."""
    company = db.scalar(select(Company).where(Company.name == SEED_ADMIN_COMPANY_NAME))
    if company is None:
        company = Company(
            name=SEED_ADMIN_COMPANY_NAME,
            code="SEEDADMIN",
            email="platform@ems-pro.internal",
            status=CompanyStatus.active,
        )
        db.add(company)
        db.flush()
    admin = db.scalar(select(User).where(User.email == SEED_ADMIN_EMAIL))
    if admin is None:
        admin = User(
            company_id=company.id,
            email=SEED_ADMIN_EMAIL,
            hashed_password=hash_password("not-a-real-login-" + fake.password(length=20)),
            role=UserRole.super_admin,
            is_active=True,
        )
        db.add(admin)
        db.flush()
    db.commit()
    return admin


def _create_company_and_approve(db: Session) -> tuple[Company, str, str]:
    print(f"Registering '{DEMO_COMPANY_NAME}'...")
    company_service = CompanyService(db)
    company = company_service.register_company(
        CompanyRegisterRequest(
            company_name=DEMO_COMPANY_NAME,
            company_email=DEMO_COMPANY_EMAIL,
            industry="Technology",
            phone="+91-80-4000-1000",
        )
    )
    seed_admin = _get_or_create_seed_admin(db)
    print("Approving it (seeds company_settings, departments, leave types, HR admin)...")
    approved, hr_email, hr_password = company_service.approve_company(company.id, seed_admin.id)
    return approved, hr_email, hr_password


def _department_lookup(db: Session, company_id) -> dict[str, Department]:
    depts = db.scalars(select(Department).where(Department.company_id == company_id)).all()
    return {d.name: d for d in depts}


# (first_name-independent) role/department distribution for the 25 employees.
_ROSTER = [
    ("Engineering", 8, True),  # (department, count, has_a_manager_among_them)
    ("Product", 3, False),
    ("Design", 2, False),
    ("Quality Assurance", 3, False),
    ("DevOps", 3, False),
    ("Sales", 4, False),
    ("Human Resources", 2, False),
]


def _create_employees(
    db: Session, company: Company, hr_user: User, departments: dict[str, Department]
) -> dict:
    """Returns {'manager_employee', 'manager_user', 'demo_employee',
    'demo_employee_user', 'all': [...]}."""
    employee_service = EmployeeService(db)
    employee_repo = EmployeeRepository(db)

    manager_employee = None
    demo_employee = None
    all_employees = []

    for dept_name, count, seed_manager_here in _ROSTER:
        dept = departments.get(dept_name)
        for i in range(count):
            first = fake.first_name()
            last = fake.last_name()
            unique_suffix = fake.unique.random_int(1000, 9999)
            email = f"{first.lower()}.{last.lower()}.{unique_suffix}@bluepeak-demo.example"
            hire_date = fake.date_between(start_date="-3y", end_date="-30d")
            data = EmployeeCreateRequest(
                first_name=first,
                last_name=last,
                email=email,
                phone=fake.numerify("9#########"),
                department_id=dept.id if dept else None,
                position=fake.job()[:150],
                level=random.choice(LEVELS),
                employment_type=random.choice(EMPLOYMENT_TYPES),
                hire_date=hire_date,
                notice_period_days=random.choice([15, 30, 60]),
            )
            employee, _raw_token = employee_service.create_employee(company.id, data, hr_user)
            all_employees.append(employee)

            if seed_manager_here and i == 0:
                manager_employee = employee
            elif dept_name == "Engineering" and i == 1 and demo_employee is None:
                demo_employee = employee

    # The manager and the demo employee both get real, activatable accounts
    # — the "one manager, one employee" credentials WP-15 asks to print.
    manager_user = User(
        company_id=company.id,
        email=manager_employee.email,
        hashed_password=hash_password(DEMO_PASSWORD),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(manager_user)
    db.flush()
    employee_repo.activate(manager_employee, user_id=manager_user.id)

    demo_employee_user = User(
        company_id=company.id,
        email=demo_employee.email,
        hashed_password=hash_password(DEMO_PASSWORD),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(demo_employee_user)
    db.flush()
    employee_repo.activate(demo_employee, user_id=demo_employee_user.id)
    demo_employee.reporting_manager_id = manager_employee.id

    # Give the manager a handful more genuine direct reports — the rest of
    # Engineering, minus the manager and the demo employee themselves.
    reports = [
        e
        for e in all_employees
        if e.department_id == manager_employee.department_id
        and e.id not in (manager_employee.id, demo_employee.id)
    ]
    for report in reports:
        report.reporting_manager_id = manager_employee.id

    db.commit()
    return {
        "manager_employee": manager_employee,
        "manager_user": manager_user,
        "demo_employee": demo_employee,
        "demo_employee_user": demo_employee_user,
        "all": all_employees,
    }


def _create_shifts(db: Session, company: Company, employees: list[Employee]) -> None:
    print("Creating shifts and assignments...")
    shift_service = ShiftService(db)
    day_shift = shift_service.create_shift(
        company.id,
        ShiftCreateRequest(name="Day Shift", start_time=time(9, 0), end_time=time(18, 0)),
    )
    night_shift = shift_service.create_shift(
        company.id,
        ShiftCreateRequest(name="Night Support", start_time=time(21, 0), end_time=time(6, 0)),
    )
    for employee in random.sample(employees, k=min(6, len(employees))):
        shift_service.assign_shift(
            company.id,
            day_shift.id,
            ShiftAssignRequest(
                employee_id=employee.id, effective_from=date.today() - timedelta(days=30)
            ),
        )
    for employee in random.sample(employees, k=min(2, len(employees))):
        try:
            shift_service.assign_shift(
                company.id,
                night_shift.id,
                ShiftAssignRequest(
                    employee_id=employee.id, effective_from=date.today() - timedelta(days=10)
                ),
            )
        except Exception:  # noqa: BLE001 — already on the day shift, skip
            pass
    db.commit()


def _create_holidays(db: Session, company: Company) -> None:
    print("Creating holidays...")
    holiday_service = HolidayService(db)
    year = date.today().year
    for name, month, day in [
        ("Republic Day", 1, 26),
        ("Independence Day", 8, 15),
        ("Gandhi Jayanti", 10, 2),
        ("Diwali", 11, 1),
    ]:
        try:
            holiday_service.create_holiday(
                company.id, HolidayCreateRequest(name=name, date=date(year, month, day))
            )
        except Exception:  # noqa: BLE001 — already exists from a previous partial run
            pass
    db.commit()


def _create_attendance(db: Session, company: Company, employees: list[Employee]) -> None:
    print(
        f"Creating ~3 months of attendance for {len(employees)} employees (this takes a moment)..."
    )
    repo = AttendanceRepository(db)
    today = date.today()
    start = today - timedelta(days=100)

    count = 0
    day = start
    while day <= today:
        if (
            day.isoweekday() <= 5
        ):  # weekdays only — no row at all for weekends (Spec 7.4's own shape)
            for employee in employees:
                if employee.hire_date > day:
                    continue
                roll = random.random()
                if roll < 0.06:
                    repo.create(
                        company_id=company.id,
                        employee_id=employee.id,
                        date=day,
                        status=AttendanceStatus.absent,
                        source=AttendanceSource.system,
                    )
                else:
                    late = roll > 0.85
                    check_in_hour = random.randint(10, 11) if late else 9
                    check_in_minute = random.randint(0, 59) if late else random.randint(0, 30)
                    check_in = datetime.combine(
                        day, time(check_in_hour, check_in_minute), tzinfo=utcnow().tzinfo
                    )
                    check_out_hour = random.randint(18, 19)
                    check_out = datetime.combine(
                        day, time(check_out_hour, random.randint(0, 45)), tzinfo=utcnow().tzinfo
                    )
                    hours = (
                        Decimal((check_out - check_in).total_seconds()) / Decimal(3600)
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    repo.create(
                        company_id=company.id,
                        employee_id=employee.id,
                        date=day,
                        check_in=check_in,
                        check_out=check_out,
                        status=AttendanceStatus.present,
                        hours_worked=hours,
                        source=AttendanceSource.web,
                        notes="Arrived late" if late else None,
                    )
                count += 1
        day += timedelta(days=1)
    db.commit()
    print(f"    {count} attendance records created.")


def _create_leave_requests(
    db: Session,
    company: Company,
    hr_user: User,
    employees: list[Employee],
    demo_employee: Employee,
    manager_employee: Employee,
) -> None:
    print("Creating leave requests (pending, approved, rejected)...")
    leave_service = LeaveService(db)
    leave_types = list(db.scalars(select(LeaveType).where(LeaveType.company_id == company.id)))
    annual = next((lt for lt in leave_types if lt.code == "annual"), leave_types[0])
    casual = next((lt for lt in leave_types if lt.code == "casual"), leave_types[0])
    sick = next((lt for lt in leave_types if lt.code == "sick"), leave_types[0])

    # demo_employee and manager_employee are the two accounts with real
    # logins — put them first so they always land on an "approved" and a
    # "rejected" outcome respectively, which is what actually generates a
    # notification (NotificationService.notify() only fires for a linked
    # user_id). Without this, a `random.sample` could easily pick ten
    # employees that have no login at all, and the demo would show an
    # empty notification bell for both accounts a reviewer can sign into.
    others = [e for e in employees if e.id not in (demo_employee.id, manager_employee.id)]
    pool = [demo_employee, manager_employee] + random.sample(others, k=min(8, len(others)))
    today = date.today()

    plans = (
        [("approved", annual, -40) for _ in range(3)]
        + [("approved", sick, -20)]
        + [("rejected", casual, -15) for _ in range(3)]
        + [("pending", annual, 15) for _ in range(2)]
        + [("pending", sick, 25)]
    )

    for employee, (outcome, leave_type, offset_days) in zip(pool, plans, strict=True):
        start = today + timedelta(days=offset_days)
        end = start + timedelta(days=random.randint(0, 2))
        try:
            leave = leave_service.apply_leave(
                company.id,
                LeaveApplyRequest(
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    start_date=start,
                    end_date=end,
                    reason=random.choice(
                        ["Family function", "Not feeling well", "Personal work", "Travel"]
                    ),
                ),
                hr_user,
            )
            if outcome == "approved":
                leave_service.decide_leave(
                    company.id, leave.id, LeaveDecisionRequest(status="approved"), hr_user
                )
            elif outcome == "rejected":
                leave_service.decide_leave(
                    company.id,
                    leave.id,
                    LeaveDecisionRequest(
                        status="rejected", rejection_reason="Insufficient team coverage that week"
                    ),
                    hr_user,
                )
            # "pending" needs no further action.
        except Exception as exc:  # noqa: BLE001 — a rare date/balance clash, skip this one
            db.rollback()
            print(f"    (skipped one leave request: {exc})")
            continue
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        _wipe_existing_demo_company(db)
        company, hr_email, hr_password = _create_company_and_approve(db)
        bind_tenant_to_session(db, company_id=company.id, is_platform_admin=False)

        departments = _department_lookup(db, company.id)
        roster = _create_employees(db, company, _hr_user(db, company, hr_email), departments)
        all_employees = roster["all"]

        _create_shifts(db, company, all_employees)
        _create_holidays(db, company)
        _create_attendance(db, company, all_employees)
        _create_leave_requests(
            db,
            company,
            _hr_user(db, company, hr_email),
            all_employees,
            demo_employee=roster["demo_employee"],
            manager_employee=roster["manager_employee"],
        )
        _regularize_one_record(
            db, company, _hr_user(db, company, hr_email), roster["demo_employee"]
        )

        print()
        print("=" * 72)
        print(f"Demo company ready: {DEMO_COMPANY_NAME} ({company.code})")
        print(f"  {len(all_employees)} employees across {len(departments)} departments")
        print("=" * 72)
        print()
        print("Log in at http://localhost:5173/login with any of these three roles:")
        print()
        print(f"  HR admin  : {hr_email} / {hr_password}")
        print(f"  Manager   : {roster['manager_user'].email} / {DEMO_PASSWORD}")
        print(f"  Employee  : {roster['demo_employee_user'].email} / {DEMO_PASSWORD}")
        print()
        print("(The HR admin password is freshly generated each run — copy it now.")
        print(f" The manager and employee passwords are always '{DEMO_PASSWORD}'.)")
    finally:
        db.close()


def _regularize_one_record(
    db: Session, company: Company, hr_user: User, employee: Employee
) -> None:
    """One HR regularization on the demo employee's own attendance — gives
    that account a genuine ATTENDANCE_REGULARIZED audit row and a
    notification too, alongside the leave-decision ones."""
    record = db.scalar(
        select(Attendance)
        .where(Attendance.company_id == company.id, Attendance.employee_id == employee.id)
        .order_by(Attendance.date.desc())
        .limit(1)
    )
    if record is None:
        return
    try:
        AttendanceService(db).regularize(
            company.id,
            record.id,
            AttendanceRegularizeRequest(
                status=AttendanceStatus.wfh, reason="Confirmed WFH with manager"
            ),
            hr_user,
        )
    except Exception as exc:  # noqa: BLE001 — cosmetic touch, never fatal
        db.rollback()
        print(f"    (skipped the demo regularization: {exc})")


def _hr_user(db: Session, company: Company, hr_email: str) -> User:
    return db.scalar(select(User).where(User.company_id == company.id, User.email == hr_email))


if __name__ == "__main__":
    main()
