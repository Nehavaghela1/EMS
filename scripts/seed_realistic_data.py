"""
Seed script to create realistic test and demo data:
1. Super Admin: Neha Vaghela (neha@infiria.com, password: neha@123)
2. 5 Distinct Realistic Companies (Infiria Systems, NexusPay Fintech, Aether Cloud Labs, Zenith Health, Solaria Energy)
3. For each company:
   - HR Admin, Managers, and Employees with realistic Indian & global names
   - Clean email format: firstname@companydomain.com (or firstname.lastname@companydomain.com if duplicate)
   - Password rule: firstname@123 (lowercase firstname + @123)
   - Real departments, attendance records, leaves, salary structures, assigned salaries, payroll runs, performance goals & reviews, projects, tasks, announcements, and documents.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.core.security import hash_password
from app.core.time import utcnow
from app.db.base import tenant_table_names
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import (
    Department,
    Employee,
    EmploymentType,
    InvitationStatus,
    ResignationStatus,
)
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole
from app.modules.payroll.models import (
    CalculationType,
    EmployeeSalary,
    PayrollItem,
    PayrollRun,
    PayrollRunStatus,
    PayrollRunType,
    PercentageOf,
    Reimbursement,
    ReimbursementStatus,
    ReimbursementType,
    SalaryComponent,
    SalaryComponentType,
    SalaryStructure,
    StatutoryConfig,
)
from app.modules.performance.models import (
    CycleStatus,
    CycleType,
    GoalStatus,
    PerformanceCycle,
    PerformanceGoal,
    PerformanceReview,
    ReviewerRole,
)
from app.modules.platform.models import (
    Announcement,
    AuditLog,
    EmployeeDocument,
    FileObject,
    Notification,
)
from app.modules.projects.models import Milestone, Project, ProjectMember, Task, TaskComment, TimeEntry
from app.modules.time_leave.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    EmployeeShift,
    Holiday,
    Leave,
    LeaveBalance,
    LeaveStatus,
    LeaveType,
    Shift,
)

# Pre-computed common passwords
PASS_NEHA = hash_password("neha@123")


def get_password(name: str) -> str:
    cleaned = name.lower().strip()
    return hash_password(f"{cleaned}@123")


def run_seed():
    db = SessionLocal()
    print("===> Starting Real Data Seeding...")

    # 1. Ensure Super Admin Neha exists
    # Find or create Infiria Systems as her base company (or platform company)
    infiria = db.query(Company).filter(Company.name == "Infiria Systems").first()
    if not infiria:
        infiria = Company(
            id=uuid.uuid4(),
            name="Infiria Systems",
            code="INFIRIA",
            email="contact@infiria.com",
            phone="+91 98765 43210",
            industry="Technology",
            country="IN",
            currency="INR",
            gst_number="24AAACI1234F1Z5",
            pan_number="AAACI1234F",
            address="Infiria Tech Park, SG Highway",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380054",
            website="https://infiria.com",
            status=CompanyStatus.active,
            approved_at=utcnow(),
        )
        db.add(infiria)
        db.flush()

    # Create/Update Super Admin Neha Vaghela
    neha_admin = db.query(User).filter(User.email == "neha@infiria.com").first()
    if not neha_admin:
        neha_admin = User(
            id=uuid.uuid4(),
            company_id=infiria.id,
            email="neha@infiria.com",
            username="neha",
            hashed_password=PASS_NEHA,
            role=UserRole.super_admin,
            is_active=True,
            must_change_password=False,
        )
        db.add(neha_admin)
        db.flush()
    else:
        neha_admin.hashed_password = PASS_NEHA
        neha_admin.role = UserRole.super_admin
        neha_admin.is_active = True
        db.flush()

    print("✔ Super Admin Neha ready: neha@infiria.com / neha@123")

    # 5 Companies configuration
    companies_data = [
        {
            "name": "Infiria Systems",
            "domain": "infiria.com",
            "code": "INFIRIA",
            "industry": "Technology",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "phone": "+91 79 4001 2000",
            "address": "Infiria Tower, Bodakdev",
            "hr_admin": ("Neha", "Vaghela", "neha@infiria.com", "neha"),
            "employees": [
                ("Aarav", "Patel", "Engineering", "Lead Architect", UserRole.manager, Decimal("1800000")),
                ("Diya", "Sharma", "Engineering", "Senior Backend Dev", UserRole.employee, Decimal("1200000")),
                ("Rohan", "Mehta", "Product", "Product Manager", UserRole.manager, Decimal("1600000")),
                ("Pooja", "Shah", "Design", "UI/UX Designer", UserRole.employee, Decimal("900000")),
                ("Kunal", "Verma", "Engineering", "DevOps Engineer", UserRole.employee, Decimal("1100000")),
                ("Sneha", "Joshi", "Human Resources", "HR Specialist", UserRole.employee, Decimal("700000")),
            ],
            "projects": [
                ("EMS Enterprise 2.0", "EMS-V2", "Core platform upgrade and dashboard", Decimal("500000")),
                ("Infiria Mobile Suite", "INF-MOB", "Cross-platform mobile apps", Decimal("350000")),
            ],
        },
        {
            "name": "NexusPay Fintech",
            "domain": "nexuspay.in",
            "code": "NEXUSPAY",
            "industry": "Financial Services",
            "city": "Mumbai",
            "state": "Maharashtra",
            "phone": "+91 22 6677 8899",
            "address": "BKC Finance Centre, Bandra East",
            "hr_admin": ("Vikram", "Malhotra", "hr@nexuspay.in", "vikram"),
            "employees": [
                ("Amit", "Kulkarni", "Risk & Fraud", "Risk Director", UserRole.manager, Decimal("2200000")),
                ("Priya", "Nair", "Engineering", "Payment Gateway Lead", UserRole.manager, Decimal("1900000")),
                ("Siddharth", "Rao", "Engineering", "Full Stack Engineer", UserRole.employee, Decimal("1300000")),
                ("Ananya", "Deshmukh", "Compliance", "KYC Officer", UserRole.employee, Decimal("850000")),
                ("Tanvi", "Bansal", "Finance", "Treasury Analyst", UserRole.employee, Decimal("950000")),
            ],
            "projects": [
                ("Instant UPI Payouts", "UPI-GATE", "High-throughput settlement gateway", Decimal("800000")),
                ("Automated KYC Flow", "KYC-AUTO", "Real-time verification pipeline", Decimal("400000")),
            ],
        },
        {
            "name": "Aether Cloud Labs",
            "domain": "aethercloud.io",
            "code": "AETHER",
            "industry": "Technology",
            "city": "Bengaluru",
            "state": "Karnataka",
            "phone": "+91 80 2345 6789",
            "address": "Indiranagar 100ft Road",
            "hr_admin": ("Aditi", "Saxena", "hr@aethercloud.io", "aditi"),
            "employees": [
                ("Karthik", "Ranganathan", "Infrastructure", "Principal SRE", UserRole.manager, Decimal("2500000")),
                ("Meera", "Swaminathan", "Infrastructure", "Cloud Architect", UserRole.employee, Decimal("1700000")),
                ("Varun", "Pillai", "Platform", "Go Backend Engineer", UserRole.employee, Decimal("1400000")),
                ("Shruti", "Iyer", "Security", "Security Analyst", UserRole.employee, Decimal("1250000")),
            ],
            "projects": [
                ("Kubernetes Auto-scaler", "K8S-SCALE", "Multi-tenant cluster optimization", Decimal("600000")),
            ],
        },
        {
            "name": "Zenith Health Tech",
            "domain": "zenithhealth.org",
            "code": "ZENITH",
            "industry": "Healthcare",
            "city": "Hyderabad",
            "state": "Telangana",
            "phone": "+91 40 4567 8901",
            "address": "Hitech City, Madhapur",
            "hr_admin": ("Rahul", "Reddy", "hr@zenithhealth.org", "rahul"),
            "employees": [
                ("Suresh", "Goud", "Clinical Ops", "Medical Director", UserRole.manager, Decimal("2400000")),
                ("Deepika", "Chowdary", "Engineering", "Telehealth Tech Lead", UserRole.manager, Decimal("1800000")),
                ("Harish", "Teja", "Engineering", "React Native Developer", UserRole.employee, Decimal("1100000")),
                ("Kavita", "Rao", "Quality Assurance", "Healthcare QA Lead", UserRole.employee, Decimal("900000")),
            ],
            "projects": [
                ("Telehealth Video Consult", "TELE-MED", "HIPAA compliant video consults", Decimal("750000")),
            ],
        },
        {
            "name": "Solaria Energy Corp",
            "domain": "solariaenergy.co",
            "code": "SOLARIA",
            "industry": "Manufacturing",
            "city": "Vadodara",
            "state": "Gujarat",
            "phone": "+91 265 233 4455",
            "address": "GIDC Industrial Estate, Makarpura",
            "hr_admin": ("Bhavin", "Pandya", "hr@solariaenergy.co", "bhavin"),
            "employees": [
                ("Jayesh", "Trivedi", "Operations", "Plant Operations Head", UserRole.manager, Decimal("2000000")),
                ("Maitri", "Doshi", "R&D", "Solar Cell Researcher", UserRole.employee, Decimal("1350000")),
                ("Chirag", "Gohil", "Quality", "Field Test Engineer", UserRole.employee, Decimal("800000")),
                ("Nirav", "Modi", "Supply Chain", "Procurement Lead", UserRole.employee, Decimal("1150000")),
            ],
            "projects": [
                ("High-Efficiency Solar Inverter", "SOL-INV", "Next-gen bifacial inverter pilot", Decimal("900000")),
            ],
        },
    ]

    for cdata in companies_data:
        comp = db.query(Company).filter(Company.name == cdata["name"]).first()
        if not comp:
            comp = Company(
                id=uuid.uuid4(),
                name=cdata["name"],
                code=cdata["code"],
                email=cdata["hr_admin"][2],
                phone=cdata["phone"],
                industry=cdata["industry"],
                country="IN",
                currency="INR",
                address=cdata["address"],
                city=cdata["city"],
                state=cdata["state"],
                pincode="380001",
                website=f"https://{cdata['domain']}",
                status=CompanyStatus.active,
                approved_at=utcnow(),
                approved_by=neha_admin.id,
            )
            db.add(comp)
            db.flush()

        bind_tenant_to_session(db, company_id=comp.id, is_platform_admin=True)

        # Company settings
        c_setting = db.query(CompanySettings).filter_by(company_id=comp.id).first()
        if not c_setting:
            c_setting = CompanySettings(company_id=comp.id)
            db.add(c_setting)
            db.flush()

        # HR Admin user
        hr_first, hr_last, hr_email, hr_user = cdata["hr_admin"]
        hr_u = db.query(User).filter(
            User.company_id == comp.id,
            (User.email == hr_email) | (User.username == hr_user)
        ).first()
        if not hr_u:
            hr_u = User(
                id=uuid.uuid4(),
                company_id=comp.id,
                email=hr_email,
                username=hr_user,
                hashed_password=get_password(hr_first),
                role=UserRole.hr_admin,
                is_active=True,
                must_change_password=False,
            )
            db.add(hr_u)
            db.flush()
        else:
            hr_u.hashed_password = get_password(hr_first)
            hr_u.is_active = True
            db.flush()

        # HR Admin Employee record
        hr_emp = db.query(Employee).filter(Employee.company_id == comp.id, Employee.email == hr_email).first()
        if not hr_emp:
            hr_emp = Employee(
                id=uuid.uuid4(),
                company_id=comp.id,
                user_id=hr_u.id,
                employee_code=f"{cdata['code'][:3]}-001",
                first_name=hr_first,
                last_name=hr_last,
                email=hr_email,
                personal_email=f"{hr_first.lower()}.personal@gmail.com",
                phone=cdata["phone"],
                position="HR Operations Manager",
                level="L5",
                employment_type=EmploymentType.full_time,
                hire_date=date(2023, 1, 15),
                is_active=True,
                invitation_status=InvitationStatus.activated,
            )
            db.add(hr_emp)
            db.flush()

        # Departments
        dept_cache = {}
        for dept_name in ["Engineering", "Product", "Design", "Human Resources", "Finance", "Operations", "Infrastructure", "Risk & Fraud", "Compliance", "Clinical Ops", "Quality Assurance", "R&D", "Supply Chain", "Quality"]:
            d = db.query(Department).filter(Department.company_id == comp.id, Department.name == dept_name).first()
            if not d:
                d = Department(id=uuid.uuid4(), company_id=comp.id, name=dept_name, description=f"{dept_name} Department")
                db.add(d)
                db.flush()
            dept_cache[dept_name] = d

        # Standard Leave Types
        leave_types = {}
        for lt_name, code, days, is_encash in [
            ("Casual Leave", "CL", 12, False),
            ("Earned / Privilege Leave", "EL", 18, True),
            ("Sick Leave", "SL", 10, False),
        ]:
            lt = db.query(LeaveType).filter(LeaveType.company_id == comp.id, LeaveType.code == code).first()
            if not lt:
                lt = LeaveType(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    name=lt_name,
                    code=code,
                    annual_allowance=Decimal(str(days)),
                    carry_forward_limit=Decimal("15.00"),
                    requires_approval=True,
                    is_paid=True,
                    is_encashable=is_encash,
                )
                db.add(lt)
                db.flush()
            leave_types[code] = lt

        # Standard Shift
        reg_shift = db.query(Shift).filter(Shift.company_id == comp.id, Shift.name == "General Day Shift").first()
        if not reg_shift:
            reg_shift = Shift(
                id=uuid.uuid4(),
                company_id=comp.id,
                name="General Day Shift",
                start_time=time(9, 30),
                end_time=time(18, 30),
                break_minutes=60,
                night_allowance=Decimal("0.00"),
                is_active=True,
            )
            db.add(reg_shift)
            db.flush()

        # Salary Structure
        sal_struct = db.query(SalaryStructure).filter(SalaryStructure.company_id == comp.id, SalaryStructure.name == "Standard Regular Structure").first()
        if not sal_struct:
            sal_struct = SalaryStructure(
                id=uuid.uuid4(),
                company_id=comp.id,
                name="Standard Regular Structure",
                country="IN",
                level="All",
                is_active=True,
            )
            db.add(sal_struct)
            db.flush()

            # Components
            comps = [
                SalaryComponent(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    structure_id=sal_struct.id,
                    code="BASIC",
                    name="Basic Pay",
                    type=SalaryComponentType.earning,
                    calculation_type=CalculationType.percentage,
                    percentage_of=PercentageOf.ctc,
                    value=Decimal("50.00"),
                    display_order=1,
                    is_taxable=True,
                ),
                SalaryComponent(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    structure_id=sal_struct.id,
                    code="HRA",
                    name="House Rent Allowance",
                    type=SalaryComponentType.earning,
                    calculation_type=CalculationType.percentage,
                    percentage_of=PercentageOf.basic,
                    value=Decimal("40.00"),
                    display_order=2,
                    is_taxable=True,
                ),
                SalaryComponent(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    structure_id=sal_struct.id,
                    code="SPECIAL_ALLOWANCE",
                    name="Special Allowance",
                    type=SalaryComponentType.earning,
                    calculation_type=CalculationType.balance,
                    display_order=3,
                    is_taxable=True,
                ),
            ]
            db.add_all(comps)
            db.flush()

        # Statutory Config
        stat_cfg = db.query(StatutoryConfig).filter(StatutoryConfig.company_id == comp.id).first()
        if not stat_cfg:
            stat_cfg = StatutoryConfig(
                id=uuid.uuid4(),
                company_id=comp.id,
                pf_enabled=True,
                pf_employee_rate=Decimal("12.00"),
                pf_employer_rate=Decimal("12.00"),
                pf_wage_ceiling=Decimal("15000.00"),
                esi_enabled=True,
                esi_employee_rate=Decimal("0.75"),
                esi_employer_rate=Decimal("3.25"),
                esi_wage_ceiling=Decimal("21000.00"),
                pt_enabled=True,
                pt_state=cdata["state"],
                tds_enabled=True,
            )
            db.add(stat_cfg)
            db.flush()

        # Employees & Users
        emp_records = []
        created_managers = {}

        # Name tracking for duplicates within company
        first_names_seen = {}

        for idx, (first_n, last_n, dept_name, pos, role, ctc) in enumerate(cdata["employees"], start=2):
            # Email naming: first@domain, or first.last@domain if duplicate
            first_lower = first_n.lower()
            if first_lower in first_names_seen:
                user_email = f"{first_lower}.{last_n.lower()}@{cdata['domain']}"
                username = f"{first_lower}.{last_n.lower()}"
            else:
                first_names_seen[first_lower] = True
                user_email = f"{first_lower}@{cdata['domain']}"
                username = first_lower

            u = db.query(User).filter(User.company_id == comp.id, User.email == user_email).first()
            if not u:
                u = User(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    email=user_email,
                    username=username,
                    hashed_password=get_password(first_n),
                    role=role,
                    is_active=True,
                    must_change_password=False,
                )
                db.add(u)
                db.flush()
            else:
                u.hashed_password = get_password(first_n)
                u.is_active = True
                db.flush()

            e = db.query(Employee).filter(Employee.company_id == comp.id, Employee.email == user_email).first()
            if not e:
                # Find manager if available
                mgr_id = None
                if role == UserRole.employee and created_managers:
                    # pick first available manager in company
                    mgr_id = list(created_managers.values())[0]

                e = Employee(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    user_id=u.id,
                    employee_code=f"{cdata['code'][:3]}-{idx:03d}",
                    first_name=first_n,
                    last_name=last_n,
                    email=user_email,
                    personal_email=f"{first_lower}.{last_n.lower()}.p@gmail.com",
                    phone=f"+91 9825{idx:02d} {idx:04d}",
                    department_id=dept_cache.get(dept_name, list(dept_cache.values())[0]).id,
                    position=pos,
                    level="L3" if role == UserRole.employee else "L4",
                    reporting_manager_id=mgr_id,
                    employment_type=EmploymentType.full_time,
                    hire_date=date(2023, 6, 1),
                    is_active=True,
                    invitation_status=InvitationStatus.activated,
                )
                db.add(e)
                db.flush()
            emp_records.append(e)

            if role == UserRole.manager:
                created_managers[dept_name] = e.id

            # Assign Shift
            emp_shift = db.query(EmployeeShift).filter_by(company_id=comp.id, employee_id=e.id).first()
            if not emp_shift:
                emp_shift = EmployeeShift(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    employee_id=e.id,
                    shift_id=reg_shift.id,
                    effective_from=date(2024, 1, 1),
                )
                db.add(emp_shift)

            # Assign Leave Balances for 2026
            for lt in leave_types.values():
                lb = db.query(LeaveBalance).filter_by(company_id=comp.id, employee_id=e.id, leave_type_id=lt.id, year=2026).first()
                if not lb:
                    lb = LeaveBalance(
                        id=uuid.uuid4(),
                        company_id=comp.id,
                        employee_id=e.id,
                        leave_type_id=lt.id,
                        year=2026,
                        opening_balance=Decimal("2.00"),
                        allocated=lt.annual_allowance,
                        used=Decimal("1.00"),
                        encashed=Decimal("0.00"),
                    )
                    db.add(lb)

            # Assign Salary
            emp_sal = db.query(EmployeeSalary).filter_by(company_id=comp.id, employee_id=e.id).first()
            if not emp_sal:
                emp_sal = EmployeeSalary(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    employee_id=e.id,
                    structure_id=sal_struct.id,
                    ctc=ctc,
                    effective_from=date(2024, 1, 1),
                    created_by=hr_u.id,
                )
                db.add(emp_sal)

            # Recent Attendance (today and past 3 days)
            for d_offset in range(4):
                att_date = date.today() - timedelta(days=d_offset)
                if att_date.weekday() < 5:  # Monday to Friday
                    att = db.query(Attendance).filter_by(company_id=comp.id, employee_id=e.id, date=att_date).first()
                    if not att:
                        cin = datetime.combine(att_date, time(9, 30))
                        cout = datetime.combine(att_date, time(18, 30))
                        att = Attendance(
                            id=uuid.uuid4(),
                            company_id=comp.id,
                            employee_id=e.id,
                            date=att_date,
                            check_in=cin,
                            check_out=cout,
                            hours_worked=Decimal("8.00"),
                            status=AttendanceStatus.present,
                            source=AttendanceSource.web,
                        )
                        db.add(att)

        # Create 1 Payroll Run for current year/month
        cur_month = date.today().month
        cur_year = date.today().year
        run = db.query(PayrollRun).filter_by(company_id=comp.id, month=cur_month, year=cur_year).first()
        if not run:
            run = PayrollRun(
                id=uuid.uuid4(),
                company_id=comp.id,
                month=cur_month,
                year=cur_year,
                status=PayrollRunStatus.paid,
                run_type=PayrollRunType.regular,
                idempotency_key=f"RUN-{comp.code}-{cur_year}-{cur_month}",
                run_by=hr_u.id,
                total_employees=len(emp_records),
                total_gross=Decimal("450000.00"),
                total_deductions=Decimal("45000.00"),
                total_net=Decimal("405000.00"),
                total_employer_cost=Decimal("470000.00"),
                approved_by=hr_u.id,
                approved_at=utcnow(),
            )
            db.add(run)
            db.flush()

            # Create payroll items for ALL employees in the company
            for emp in emp_records:
                existing_item = db.query(PayrollItem).filter_by(company_id=comp.id, payroll_run_id=run.id, employee_id=emp.id).first()
                if not existing_item:
                    item = PayrollItem(
                        id=uuid.uuid4(),
                        company_id=comp.id,
                        payroll_run_id=run.id,
                        employee_id=emp.id,
                        ctc_snapshot=Decimal("1200000.00"),
                        gross_salary=Decimal("100000.00"),
                        total_deductions=Decimal("12000.00"),
                        net_salary=Decimal("88000.00"),
                        employer_cost=Decimal("105000.00"),
                        earnings_json=[{"code": "BASIC", "name": "Basic Pay", "amount": 50000.0}, {"code": "HRA", "name": "House Rent Allowance", "amount": 25000.0}],
                        deductions_json=[{"code": "EPF_EE", "name": "Employee PF", "amount": 1800.0}, {"code": "PT", "name": "Professional Tax", "amount": 200.0}],
                        employer_contributions_json=[{"code": "EPF_ER", "name": "Employer PF", "amount": 1800.0}],
                        working_days=Decimal("22.00"),
                        present_days=Decimal("22.00"),
                        absent_days=Decimal("0.00"),
                        half_days=Decimal("0.00"),
                        paid_leave_days=Decimal("0.00"),
                        lop_days=Decimal("0.00"),
                        reimbursement_amount=Decimal("0.00"),
                    )
                    db.add(item)

        # Projects & Tasks
        for p_name, p_code, p_desc, p_budget in cdata["projects"]:
            p = db.query(Project).filter(Project.company_id == comp.id, Project.code == p_code).first()
            if not p:
                lead_mgr = list(created_managers.values())[0] if created_managers else hr_emp.id
                p = Project(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    name=p_name,
                    code=p_code,
                    description=p_desc,
                    status="active",
                    start_date=date.today() - timedelta(days=30),
                    deadline=date.today() + timedelta(days=90),
                    budget=p_budget,
                    manager_id=lead_mgr,
                    client_name="Global Enterprise Client",
                )
                db.add(p)
                db.flush()

                # Add members
                for emp in emp_records[:3]:
                    pm = ProjectMember(
                        id=uuid.uuid4(),
                        company_id=comp.id,
                        project_id=p.id,
                        employee_id=emp.id,
                        role="member",
                    )
                    db.add(pm)

                # Add 2 Tasks
                t1 = Task(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    project_id=p.id,
                    title="Architecture Review & API Design",
                    description="Finalize database ERD and OpenAPI specifications",
                    assigned_to=emp_records[0].id if emp_records else None,
                    priority="high",
                    status="completed",
                    estimated_hours=Decimal("24.00"),
                    completed_at=datetime.utcnow(),
                )
                t2 = Task(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    project_id=p.id,
                    title="Component Library & Frontend Pages",
                    description="Build responsive React layouts with theme consistency",
                    assigned_to=emp_records[1].id if len(emp_records) > 1 else None,
                    priority="medium",
                    status="in_progress",
                    estimated_hours=Decimal("40.00"),
                )
                db.add_all([t1, t2])
                db.flush()

                # Time entries
                te = TimeEntry(
                    id=uuid.uuid4(),
                    company_id=comp.id,
                    employee_id=emp_records[0].id,
                    project_id=p.id,
                    task_id=t1.id,
                    date=date.today() - timedelta(days=1),
                    hours=Decimal("7.50"),
                    description="Designed schemas and verified API contracts",
                    status="approved",
                    approved_by=hr_u.id,
                )
                db.add(te)

        # Announcements
        ann = db.query(Announcement).filter(Announcement.company_id == comp.id).first()
        if not ann:
            ann = Announcement(
                id=uuid.uuid4(),
                company_id=comp.id,
                title=f"Welcome to {comp.name} on EMS Pro Platform",
                content="All employees and managers can now track attendance, apply for leaves, access salary slips, and manage project timesheets directly through the portal.",
                target_role="all",
                created_by=hr_u.id,
            )
            db.add(ann)

        db.commit()
        print(f"✔ Successfully seeded company '{comp.name}' ({cdata['domain']}) with {len(emp_records)+1} employees!")

    db.close()
    print("===> Data seeding complete!")


if __name__ == "__main__":
    run_seed()
