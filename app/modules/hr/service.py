import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email_templates import employee_invitation_email
from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.core.security import generate_refresh_token, hash_token
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee, EmploymentType, InvitationStatus, ResignationStatus
from app.modules.hr.repository import DepartmentRepository, EmployeeRepository
from app.modules.hr.schemas import (
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
    ResignationSubmitRequest,
    ResignationApproveRequest,
    TerminationRequest,
    FnFClearanceUpdateRequest,
    FnFSettlementResponse,
)
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import CompanyRepository, UserRepository
from app.modules.platform.service import AuditService, DashboardService, jsonable
from app.workers.tasks.email import send_email_task


class InvalidReferenceError(AppError):
    """A body field references another resource that doesn't exist in this
    company — a business-rule violation (400 per 10.1's status table), not a
    request-body schema failure (422, reserved for FastAPI's own
    RequestValidationError)."""

    status_code = 400
    code = "invalid_reference"


class DepartmentService:
    """Routes 31-35 (10.3)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = DepartmentRepository(db)
        self.employee_repo = EmployeeRepository(db)

    def _get_or_404(self, company_id: uuid.UUID, department_id: uuid.UUID) -> Department:
        department = self.repo.get_by_id(department_id, company_id)
        if department is None:
            raise NotFoundError("Department not found.")
        return department

    def list_departments(
        self, company_id: uuid.UUID, *, q: str | None, sort: str | None, page_params: PageParams
    ) -> tuple[list[Department], int, int, dict[uuid.UUID, int]]:
        items, total, pages = self.repo.list_departments(
            company_id=company_id, q=q, sort=sort, page_params=page_params
        )
        counts = self.repo.employee_counts(company_id, [d.id for d in items])
        return items, total, pages, counts

    def create_department(
        self, company_id: uuid.UUID, data: DepartmentCreateRequest
    ) -> tuple[Department, int]:
        if self.repo.get_by_name(company_id, data.name):
            raise ConflictError("A department with this name already exists.")
        department = self.repo.create(
            company_id=company_id, name=data.name, description=data.description
        )
        self.db.commit()
        return department, 0

    def get_department(
        self, company_id: uuid.UUID, department_id: uuid.UUID
    ) -> tuple[Department, int]:
        department = self._get_or_404(company_id, department_id)
        count = self.repo.count_active_employees(company_id, department_id)
        return department, count

    def update_department(
        self, company_id: uuid.UUID, department_id: uuid.UUID, data: DepartmentUpdateRequest
    ) -> tuple[Department, int]:
        department = self._get_or_404(company_id, department_id)
        updates = data.model_dump(exclude_unset=True)
        new_name = updates.get("name")
        if new_name and new_name.lower() != department.name.lower():
            if self.repo.get_by_name(company_id, new_name):
                raise ConflictError("A department with this name already exists.")
        if "head_employee_id" in updates and updates["head_employee_id"] is not None:
            head = self.employee_repo.get_by_id_any_status(updates["head_employee_id"], company_id)
            if head is None:
                raise InvalidReferenceError(
                    "The specified head employee does not exist.",
                    details={"field": "head_employee_id"},
                )
        self.repo.update(department, **updates)
        self.db.commit()
        count = self.repo.count_active_employees(company_id, department_id)
        return department, count

    def delete_department(self, company_id: uuid.UUID, department_id: uuid.UUID) -> None:
        department = self._get_or_404(company_id, department_id)
        # Route 35 (10.3): blocked with 409 + the count when active employees
        # are assigned. `employees` didn't exist until this package (WP-07) —
        # this was WP-06's one open gap, closed now.
        count = self.repo.count_active_employees(company_id, department_id)
        if count > 0:
            raise ConflictError(
                f"Cannot delete a department with {count} active employee(s) assigned.",
                details={"employee_count": count},
            )
        self.repo.soft_delete(department)
        self.db.commit()


# The two fields an "Own" caller may change on their own employee record
# (Spec 10.3 route 23: "employees may edit only contact fields; department,
# level, manager and dates are HR-only"). `email` is treated as the
# administrative work-email field, HR-only alongside those.
CONTACT_FIELDS = {"last_name", "personal_email", "phone"}


def get_policy_notice_days(level: str | None, is_probation: bool = False, custom_days: int | None = None) -> int:
    """Calculate contractual notice period by level/band or probation according to policy:
    - Probation: 15 days
    - L1: 30 days
    - L2: 60 days
    - L3+: 90 days
    - Default: 30 days
    If custom_days is explicitly non-standard (>0 and != 30), respect it."""
    if custom_days and custom_days not in (0, 30):
        return custom_days
    if is_probation:
        return 15
    if level == "L3":
        return 90
    if level == "L2":
        return 60
    if level == "L1":
        return 30
    return custom_days if custom_days else 30


class EmployeeService:
    """Routes 19-26 (10.3), employee_code generation (11.2)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = EmployeeRepository(db)
        self.department_repo = DepartmentRepository(db)
        self.company_repo = CompanyRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    def _get_or_404(self, company_id: uuid.UUID | None, employee_id: uuid.UUID) -> Employee:
        if company_id is None:
            # Platform admin direct lookup by employee_id across companies
            employee = self.db.scalar(
                select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None))
            )
        else:
            employee = self.repo.get_by_id_any_status(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        return employee

    def _validate_department(self, company_id: uuid.UUID, department_id: uuid.UUID | None) -> None:
        if department_id is None:
            return
        if self.department_repo.get_by_id(department_id, company_id) is None:
            raise InvalidReferenceError(
                "The specified department does not exist.", details={"field": "department_id"}
            )

    def _validate_manager(
        self,
        company_id: uuid.UUID,
        manager_id: uuid.UUID | None,
        *,
        self_id: uuid.UUID | None = None,
    ) -> None:
        if manager_id is None:
            return
        if self_id is not None and manager_id == self_id:
            raise InvalidReferenceError(
                "An employee cannot be their own reporting manager.",
                details={"field": "reporting_manager_id"},
            )
        if self.repo.get_by_id_any_status(manager_id, company_id) is None:
            raise InvalidReferenceError(
                "The specified reporting manager does not exist.",
                details={"field": "reporting_manager_id"},
            )

    def list_employees(
        self,
        company_id: uuid.UUID | None,
        current_user: User,
        *,
        q: str | None,
        department_id: uuid.UUID | None,
        is_active: bool | None,
        level: str | None,
        employment_type: EmploymentType | None,
        reporting_manager_id: uuid.UUID | None,
        sort: str | None,
        page_params: PageParams,
    ) -> tuple[list[Employee], int, int]:
        """Route 19. A manager sees only their own direct reports, no matter
        what `reporting_manager_id` the client sent — the server overrides
        it, it never trusts the caller's own claim of scope."""
        target_company_id = company_id
        if current_user.role != UserRole.super_admin:
            target_company_id = current_user.company_id

        if current_user.role == UserRole.manager:
            caller_employee = self.repo.get_by_user_id(current_user.company_id, current_user.id)
            if caller_employee is None:
                return [], 0, 0
            reporting_manager_id = caller_employee.id
        return self.repo.list_employees(
            company_id=target_company_id,
            q=q,
            department_id=department_id,
            is_active=is_active,
            level=level,
            employment_type=employment_type,
            reporting_manager_id=reporting_manager_id,
            sort=sort,
            page_params=page_params,
        )

    def _send_activation_email(
        self, company_id: uuid.UUID, employee: Employee, raw_token: str
    ) -> str:
        """Shared by create_employee and resend_invite. Sent to the
        employee's PERSONAL email, never their work one — they cannot reach
        a work inbox before they have an account to reach it with. Falls
        back to the work email only when no personal one was given, so
        invitation creation is never blocked on it (personal_email stays an
        optional field — see Part 3 recommendations for making it required).
        Returns the address it was sent to, for the API response.
        """
        company = self.company_repo.get_by_id(company_id)
        assert company is not None  # FK guarantees this
        sent_to = employee.personal_email or employee.email
        activation_link = f"{settings.FRONTEND_BASE_URL}/activate/{raw_token}"
        assert employee.activation_expires_at is not None
        subject, text_body, html_body = employee_invitation_email(
            first_name=employee.first_name,
            company_name=company.name,
            activation_link=activation_link,
            expires_at=employee.activation_expires_at,
        )
        send_email_task.delay(to=sent_to, subject=subject, text_body=text_body, html_body=html_body)
        return sent_to

    def create_employee(
        self, company_id: uuid.UUID, data: EmployeeCreateRequest, actor: User
    ) -> tuple[Employee, str]:
        """Route 20. employee_code (11.2) and the activation token are both
        generated inside the one transaction this method commits (6.7)."""
        if self.repo.get_by_email(company_id, data.email):
            raise ConflictError("An employee with this email already exists in your company.")
        self._validate_department(company_id, data.department_id)
        self._validate_manager(company_id, data.reporting_manager_id)

        seq, company_code = self.company_repo.increment_employee_seq(company_id)
        employee_code = f"{company_code}-{seq:04d}"

        raw_token = generate_refresh_token()
        employee = self.repo.create(
            company_id=company_id,
            employee_code=employee_code,
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            personal_email=data.personal_email,
            phone=data.phone,
            department_id=data.department_id,
            position=data.position,
            level=data.level,
            reporting_manager_id=data.reporting_manager_id,
            employment_type=data.employment_type,
            hire_date=data.hire_date,
            probation_end_date=data.probation_end_date,
            notice_period_days=get_policy_notice_days(
                level=data.level,
                is_probation=bool(data.probation_end_date and data.probation_end_date > data.hire_date),
                custom_days=data.notice_period_days,
            ),
            invitation_status=InvitationStatus.sent,
            activation_token_hash=hash_token(raw_token),
            activation_expires_at=utcnow() + timedelta(days=settings.INVITE_TOKEN_EXPIRE_DAYS),
        )
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_CREATED",
            entity_type="employee",
            entity_id=employee.id,
            details={"employee_code": employee_code, "email": employee.email},
        )
        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)
        sent_to = self._send_activation_email(company_id, employee, raw_token)
        return employee, sent_to

    def get_my_employee_record(self, company_id: uuid.UUID, current_user: User) -> Employee:
        """Route 21."""
        employee = self.repo.get_by_user_id(company_id, current_user.id)
        if employee is None:
            raise NotFoundError("You do not have an employee record.")
        return employee

    def _assert_can_view(
        self, company_id: uuid.UUID | None, employee: Employee, current_user: User
    ) -> None:
        if current_user.role in (UserRole.hr_admin, UserRole.super_admin):
            return
        if employee.user_id == current_user.id:
            return
        if current_user.role == UserRole.manager:
            caller_employee = self.repo.get_by_user_id(current_user.company_id, current_user.id)
            if caller_employee is not None and employee.reporting_manager_id == caller_employee.id:
                return
        raise ForbiddenError("You do not have permission to view this employee.")

    def get_employee(
        self, company_id: uuid.UUID | None, employee_id: uuid.UUID, current_user: User
    ) -> Employee:
        """Route 22: Own, Mgr (own reports only), HR, Super Admin."""
        lookup_company_id = None if current_user.role == UserRole.super_admin else company_id
        employee = self._get_or_404(lookup_company_id, employee_id)
        self._assert_can_view(lookup_company_id, employee, current_user)
        return employee

    def update_employee(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        data: EmployeeUpdateRequest,
        current_user: User,
    ) -> Employee:
        """Route 23: Own, HR — never Mgr. Own may set only contact fields."""
        employee = self._get_or_404(company_id, employee_id)
        is_hr = current_user.role == UserRole.hr_admin
        is_own = employee.user_id == current_user.id
        if not is_hr and not is_own:
            raise ForbiddenError("You do not have permission to update this employee.")

        updates = data.model_dump(exclude_unset=True)
        if not is_hr:
            restricted = set(updates) - CONTACT_FIELDS
            if restricted:
                raise ForbiddenError(
                    "You may only update your own contact details.",
                    details={"fields": sorted(restricted)},
                )

        new_email = updates.get("email")
        if new_email and new_email.lower() != employee.email.lower():
            if self.repo.get_by_email(company_id, new_email):
                raise ConflictError("An employee with this email already exists in your company.")

        if "department_id" in updates:
            self._validate_department(company_id, updates["department_id"])
        if "reporting_manager_id" in updates:
            self._validate_manager(company_id, updates["reporting_manager_id"], self_id=employee.id)

        # `EmployeeUpdateRequest` (schemas.py) has no password/token/Aadhaar/
        # PAN/bank field to begin with, so every key `updates` can contain
        # is already safe to log by construction — still passed through
        # AuditService.record's own denylist as the backstop, not the
        # primary control (Spec 7.8).
        diff = {
            field: {"from": jsonable(getattr(employee, field)), "to": jsonable(new_value)}
            for field, new_value in updates.items()
        }
        self.repo.update(employee, **updates)
        self.audit.record(
            company_id=company_id,
            actor=current_user,
            action="EMPLOYEE_UPDATED",
            entity_type="employee",
            entity_id=employee.id,
            details=diff,
        )
        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)
        return employee

    def deactivate_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User
    ) -> None:
        """Route 24: soft deactivate — never a hard delete (6.5). The row
        stays in the database; `is_active=False` also gates it out of
        `get_by_id`, so it 404s by id afterward. The linked user (if any) is
        deactivated too, so login and refresh both reject it immediately
        (9.2's "reject if is_active is false")."""
        employee = self._get_or_404(company_id, employee_id)
        self.repo.update(employee, is_active=False)
        if employee.user_id is not None:
            user = self.user_repo.get_by_id(employee.user_id, company_id)
            if user is not None:
                self.user_repo.update(user, company_id, is_active=False)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_DEACTIVATED",
            entity_type="employee",
            entity_id=employee.id,
            details={"employee_code": employee.employee_code},
        )
        self.db.commit()
        DashboardService.invalidate_company_dashboards(company_id)

    def reactivate_employee(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
        """Route 25 (`/toggle-active`, spec's literal path name) — reactivate.
        Must look the employee up without the is_active filter, since the
        whole point is finding an already-deactivated row."""
        employee = self.repo.get_by_id_any_status(employee_id, company_id)
        if employee is None:
            raise NotFoundError("Employee not found.")
        self.repo.update(employee, is_active=True)
        if employee.user_id is not None:
            user = self.user_repo.get_by_id(employee.user_id, company_id)
            if user is not None:
                self.user_repo.update(user, company_id, is_active=True)
        self.db.commit()
        return employee

    def resend_invite(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> tuple[Employee, str]:
        """Route 26: a fresh activation token, on a fresh clock — invalidates
        whatever link was already sent (a new hash overwrites the old one),
        then re-sends via _send_activation_email."""
        employee = self._get_or_404(company_id, employee_id)
        raw_token = generate_refresh_token()
        self.repo.update(
            employee,
            invitation_status=InvitationStatus.sent,
            activation_token_hash=hash_token(raw_token),
            activation_expires_at=utcnow() + timedelta(days=settings.INVITE_TOKEN_EXPIRE_DAYS),
        )
        self.db.commit()
        sent_to = self._send_activation_email(company_id, employee, raw_token)
        return employee, sent_to

    # ── Resignation & Full-and-Final (Routes 27-30) ─────────────────
    def submit_resignation(self, company_id: uuid.UUID, employee_id: uuid.UUID, data: ResignationSubmitRequest) -> Employee:
        employee = self._get_or_404(company_id, employee_id)
        if employee.resignation_status == ResignationStatus.submitted:
            raise ConflictError("Resignation is already submitted.")

        # Calculate served days and notice recovery shortfall
        served_days = max(0, (data.last_working_date - data.resignation_date).days)
        notice_required = employee.notice_period_days or 30
        shortfall_days = max(0, notice_required - served_days)

        self.repo.update(
            employee,
            resignation_status=ResignationStatus.submitted,
            resignation_date=data.resignation_date,
            last_working_date=data.last_working_date,
            separation_type="voluntary",
            notice_recovery_days=shortfall_days,
            notice_waived=False,
        )
        self.db.commit()
        return employee

    def approve_resignation(self, company_id: uuid.UUID, employee_id: uuid.UUID, data: ResignationApproveRequest) -> Employee:
        employee = self._get_or_404(company_id, employee_id)
        if not data.approved:
            self.repo.update(employee, resignation_status=ResignationStatus.rejected)
        else:
            self.repo.update(
                employee,
                resignation_status=ResignationStatus.approved,
                last_working_date=data.last_working_date or employee.last_working_date,
                notice_waived=data.notice_waived,
                notice_recovery_days=data.notice_recovery_days if not data.notice_waived else 0,
            )
        self.db.commit()
        return employee

    def terminate_employee(self, company_id: uuid.UUID, employee_id: uuid.UUID, data: TerminationRequest, actor: User) -> Employee:
        employee = self._get_or_404(company_id, employee_id)
        # Schedule separation / involuntary termination
        # Severance pay or notice pay in lieu can be configured
        total_severance = Decimal(str(data.severance_pay)) + Decimal(str(data.notice_pay_in_lieu))
        self.repo.update(
            employee,
            is_active=False,
            resignation_status=ResignationStatus.approved,
            separation_type="involuntary",
            termination_reason=data.reason,
            last_working_date=data.termination_date,
            severance_pay=total_severance,
            notice_waived=True,
            notice_recovery_days=0,
        )
        # If employee has user account, deactivate it on termination date
        if employee.user_id and data.termination_date <= utcnow().date():
            user = self.db.scalar(select(User).where(User.id == employee.user_id))
            if user:
                user.is_active = False

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_TERMINATED",
            entity_type="employee",
            entity_id=employee.id,
            details={"reason": data.reason, "termination_date": str(data.termination_date), "severance": str(total_severance)},
        )
        self.db.commit()
        return employee

    def calculate_fnf(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> FnFSettlementResponse:
        employee = self._get_or_404(company_id, employee_id)
        last_working = employee.last_working_date or utcnow().date()
        
        # Calculate notice recovery / shortfall
        notice_required = employee.notice_period_days
        notice_served = (last_working - (employee.resignation_date or last_working)).days if employee.resignation_date else notice_required
        notice_recovery_days = employee.notice_recovery_days if not employee.notice_waived else 0

        # Calculate salary and daily rate from in-force salary assignment or latest payslip
        from app.modules.payroll.repository import EmployeeSalaryRepository, SalaryStructureRepository, PayrollItemRepository, StatutoryConfigRepository
        from app.modules.payroll.payslip_engine import PayslipInput, StatutoryConfigSpec, ComponentSpec, calculate_payslip
        salary_repo = EmployeeSalaryRepository(self.db)
        payroll_item_repo = PayrollItemRepository(self.db)

        # 1. Try in-force salary on last_working date, then open-ended, then latest recorded salary
        active_sal = (
            salary_repo.get_in_force(employee.id, company_id, last_working)
            or salary_repo.get_open_ended(employee.id, company_id)
            or salary_repo.get_latest(employee.id, company_id)
        )
        
        monthly_gross = Decimal("0.00")
        monthly_basic = Decimal("0.00")
        per_day_basic = Decimal("0.00")
        per_day_gross = Decimal("0.00")

        if active_sal:
            struct = SalaryStructureRepository(self.db).get_by_id(active_sal.structure_id, company_id)
            if struct:
                stat_row = StatutoryConfigRepository(self.db).get_by_company(company_id)
                stat_spec = StatutoryConfigSpec(
                    pf_enabled=stat_row.pf_enabled if stat_row else True,
                    pf_employee_rate=stat_row.pf_employee_rate if stat_row else Decimal("12.000"),
                    pf_employer_rate=stat_row.pf_employer_rate if stat_row else Decimal("12.000"),
                    pf_wage_ceiling=stat_row.pf_wage_ceiling if stat_row else Decimal("15000.00"),
                    pf_restrict_to_ceiling=stat_row.pf_restrict_to_ceiling if stat_row else True,
                    esi_enabled=stat_row.esi_enabled if stat_row else True,
                    esi_employee_rate=stat_row.esi_employee_rate if stat_row else Decimal("0.750"),
                    esi_employer_rate=stat_row.esi_employer_rate if stat_row else Decimal("3.250"),
                    esi_wage_ceiling=stat_row.esi_wage_ceiling if stat_row else Decimal("21000.00"),
                    pt_enabled=stat_row.pt_enabled if stat_row else True,
                    pt_state=stat_row.pt_state if stat_row else "Gujarat",
                    tds_enabled=stat_row.tds_enabled if stat_row else True,
                    default_tax_regime=stat_row.default_tax_regime if stat_row else "new",
                )
                comp_specs = [
                    ComponentSpec(
                        code=c.code,
                        name=c.name,
                        type=c.type.value if hasattr(c.type, "value") else c.type,
                        calculation_type=c.calculation_type.value if hasattr(c.calculation_type, "value") else c.calculation_type,
                        value=c.value,
                        percentage_of=c.percentage_of.value if hasattr(c.percentage_of, "value") and c.percentage_of else c.percentage_of,
                        is_taxable=c.is_taxable,
                        is_statutory=c.is_statutory,
                        display_order=c.display_order,
                    )
                    for c in struct.components
                ]
                p_in = PayslipInput(
                    ctc_annual=active_sal.ctc,
                    components=comp_specs,
                    statutory=stat_spec,
                    pt_slabs=[],
                    tax_slabs=[],
                    month=last_working.month,
                    year=last_working.year,
                    financial_year=f"{last_working.year}-{last_working.year+1}",
                    working_days=Decimal("30"),
                    present_days=Decimal("30"),
                    paid_leave_days=Decimal("0"),
                    lop_days=Decimal("0"),
                )
                p_out = calculate_payslip(p_in)
                monthly_gross = p_out.gross_salary
                basic_comp = next((e for e in p_out.earnings if e.code == "BASIC"), None)
                monthly_basic = basic_comp.amount if basic_comp else monthly_gross * Decimal("0.40")

        # 2. If no salary structure or gross resolved to 0, check latest payslip snapshot
        if monthly_gross <= Decimal("0.00"):
            recent_payslips = payroll_item_repo.list_by_employee_id(company_id, employee.id)
            if recent_payslips:
                latest_slip = recent_payslips[0]
                monthly_gross = latest_slip.gross_salary
                # Find basic from earnings_json if available
                basic_in_slip = next(
                    (Decimal(str(e.get("amount", 0))) for e in (latest_slip.earnings_json or []) if e.get("code") == "BASIC"),
                    None,
                )
                monthly_basic = basic_in_slip if basic_in_slip is not None else monthly_gross * Decimal("0.40")

        # Daily rate calculation: monthly / 30
        if monthly_gross > Decimal("0.00"):
            per_day_gross = (monthly_gross / Decimal("30")).quantize(Decimal("0.01"))
            per_day_basic = (monthly_basic / Decimal("30")).quantize(Decimal("0.01"))

        notice_recovery_amount = (Decimal(str(notice_recovery_days)) * per_day_gross).quantize(Decimal("0.01"))

        # Encashable leave balance
        from app.modules.time_leave.repository import LeaveBalanceRepository, LeaveTypeRepository
        leave_type_repo = LeaveTypeRepository(self.db)
        balances = LeaveBalanceRepository(self.db).list_for_employee_year(employee.id, last_working.year)
        encashable_days = Decimal("0.0")
        for b in balances:
            lt = leave_type_repo.get_by_id(b.leave_type_id, company_id)
            if lt and lt.is_encashable:
                available = b.opening_balance + b.allocated - b.used - b.encashed
                if available > 0:
                    encashable_days += available

        leave_encashment_amount = (encashable_days * per_day_basic).quantize(Decimal("0.01"))
        unpaid_salary_days = last_working.day
        unpaid_salary_amount = (Decimal(str(unpaid_salary_days)) * per_day_gross).quantize(Decimal("0.01"))

        # Extra FnF components: severance, reimbursements, gratuity, asset deductions
        severance_pay = Decimal(str(employee.severance_pay or 0)).quantize(Decimal("0.01"))
        pending_reimbursements = Decimal(str(employee.pending_reimbursements or 0)).quantize(Decimal("0.01"))
        gratuity_bonus = Decimal(str(employee.gratuity_bonus or 0)).quantize(Decimal("0.01"))
        asset_deductions = Decimal(str(employee.asset_deductions or 0)).quantize(Decimal("0.01"))

        # Net Formula:
        # FnF Net Payout = (Payable Days Salary + Encashable Leaves + Pending Reimbursements + Gratuity/Bonus + Severance)
        #                  - (Notice Shortfall Recovery + Asset Damage/Deductions)
        total_additions = unpaid_salary_amount + leave_encashment_amount + pending_reimbursements + gratuity_bonus + severance_pay
        total_deductions = notice_recovery_amount + asset_deductions
        total_settlement = (total_additions - total_deductions).quantize(Decimal("0.01"))

        can_release = bool(employee.it_clearance and employee.hr_clearance and employee.finance_clearance)

        return FnFSettlementResponse(
            employee_id=employee.id,
            employee_name=f"{employee.first_name} {employee.last_name or ''}".strip(),
            last_working_date=last_working,
            separation_type=employee.separation_type or "voluntary",
            termination_reason=employee.termination_reason,
            notice_days_required=notice_required,
            notice_days_served=max(0, notice_served),
            notice_waived=employee.notice_waived,
            notice_recovery_days=notice_recovery_days,
            notice_recovery_amount=notice_recovery_amount,
            encashable_leave_days=encashable_days,
            leave_encashment_amount=leave_encashment_amount,
            unpaid_salary_days=unpaid_salary_days,
            unpaid_salary_amount=unpaid_salary_amount,
            monthly_gross_salary=monthly_gross,
            per_day_salary=per_day_gross,
            severance_pay=severance_pay,
            pending_reimbursements=pending_reimbursements,
            gratuity_bonus=gratuity_bonus,
            asset_deductions=asset_deductions,
            it_clearance=employee.it_clearance,
            hr_clearance=employee.hr_clearance,
            finance_clearance=employee.finance_clearance,
            can_release_settlement=can_release,
            fnf_settled_at=employee.fnf_settled_at,
            total_settlement_amount=total_settlement,
        )

    def update_fnf_clearance(self, company_id: uuid.UUID, employee_id: uuid.UUID, data: FnFClearanceUpdateRequest, actor: User) -> FnFSettlementResponse:
        employee = self._get_or_404(company_id, employee_id)
        updates = {}
        if data.it_clearance is not None:
            updates["it_clearance"] = data.it_clearance
        if data.hr_clearance is not None:
            updates["hr_clearance"] = data.hr_clearance
        if data.finance_clearance is not None:
            updates["finance_clearance"] = data.finance_clearance
        if data.severance_pay is not None:
            updates["severance_pay"] = data.severance_pay
        if data.pending_reimbursements is not None:
            updates["pending_reimbursements"] = data.pending_reimbursements
        if data.gratuity_bonus is not None:
            updates["gratuity_bonus"] = data.gratuity_bonus
        if data.asset_deductions is not None:
            updates["asset_deductions"] = data.asset_deductions
        if data.mark_settled:
            updates["fnf_settled_at"] = utcnow()
            # Ensure employee is marked inactive upon settlement
            updates["is_active"] = False

        if updates:
            self.repo.update(employee, **updates)
            self.db.commit()

        return self.calculate_fnf(company_id, employee_id)
