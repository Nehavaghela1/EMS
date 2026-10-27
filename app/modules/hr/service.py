import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email_templates import employee_invitation_email
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.masking import mask_tail
from app.core.pagination import PageParams
from app.core.roles import HR_LEVEL_ROLES
from app.core.security import generate_refresh_token, hash_token
from app.core.time import utcnow
from app.modules.hr.models import (
    Department,
    Employee,
    EmploymentType,
    InvitationStatus,
    ResignationStatus,
)
from app.modules.hr.repository import (
    DepartmentRepository,
    EmployeeRepository,
    EmployeeSectionRepository,
)
from app.modules.hr.schemas import (
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
    FnFClearanceUpdateRequest,
    FnFSettlementResponse,
    ResignationApproveRequest,
    ResignationSubmitRequest,
    TerminationRequest,
)
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import (
    CompanyLocationRepository,
    CompanyRepository,
    RefreshTokenRepository,
    UserRepository,
)
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
        self.audit = AuditService(db)

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

    def _validate_head_employee(
        self, company_id: uuid.UUID, head_employee_id: uuid.UUID | None
    ) -> None:
        if head_employee_id is None:
            return
        head = self.employee_repo.get_by_id_any_status(head_employee_id, company_id)
        if (
            head is None
            or head.company_id != company_id
            or not head.is_active
            or head.deleted_at is not None
        ):
            raise InvalidReferenceError(
                "The specified head employee does not exist or is inactive.",
                details={"field": "head_employee_id"},
            )

    def create_department(
        self, company_id: uuid.UUID, data: DepartmentCreateRequest, actor: User | None = None
    ) -> tuple[Department, int]:
        clean_name = data.name.strip()
        if self.repo.get_by_name(company_id, clean_name):
            raise ConflictError("A department with this name already exists.")

        self._validate_head_employee(company_id, data.head_employee_id)

        try:
            department = self.repo.create(
                company_id=company_id,
                name=clean_name,
                description=data.description,
                head_employee_id=data.head_employee_id,
                clearance_function=data.clearance_function,
            )
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="DEPARTMENT_CREATED",
                entity_type="department",
                entity_id=department.id,
                details={"name": clean_name},
            )
            self.db.commit()
            return department, 0
        except IntegrityError as exc:
            self.db.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint in (
                "uq_departments_company_lower_name",
                "uq_departments_company_id_name",
            ):
                raise ConflictError("A department with this name already exists.") from exc
            raise

    def get_department(
        self, company_id: uuid.UUID, department_id: uuid.UUID
    ) -> tuple[Department, int]:
        department = self._get_or_404(company_id, department_id)
        count = self.repo.count_active_employees(company_id, department_id)
        return department, count

    def update_department(
        self,
        company_id: uuid.UUID,
        department_id: uuid.UUID,
        data: DepartmentUpdateRequest,
        actor: User | None = None,
    ) -> tuple[Department, int]:
        department = self._get_or_404(company_id, department_id)
        updates = data.model_dump(exclude_unset=True)
        if "name" in updates and updates["name"] is not None:
            updates["name"] = updates["name"].strip()
            new_name = updates["name"]
            if new_name.lower() != department.name.lower():
                if self.repo.get_by_name(company_id, new_name):
                    raise ConflictError("A department with this name already exists.")

        if "head_employee_id" in updates:
            self._validate_head_employee(company_id, updates["head_employee_id"])

        diff = {}
        for field, new_value in updates.items():
            old_value = getattr(department, field)
            if old_value != new_value:
                diff[field] = {"from": jsonable(old_value), "to": jsonable(new_value)}

        try:
            self.repo.update(department, **updates)
            if diff:
                self.audit.record(
                    company_id=company_id,
                    actor=actor,
                    action="DEPARTMENT_UPDATED",
                    entity_type="department",
                    entity_id=department.id,
                    details=diff,
                )
            self.db.commit()
            count = self.repo.count_active_employees(company_id, department_id)
            return department, count
        except IntegrityError as exc:
            self.db.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint in (
                "uq_departments_company_lower_name",
                "uq_departments_company_id_name",
            ):
                raise ConflictError("A department with this name already exists.") from exc
            raise

    def delete_department(
        self, company_id: uuid.UUID, department_id: uuid.UUID, actor: User | None = None
    ) -> None:
        department = self._get_or_404(company_id, department_id)
        count = self.repo.count_active_employees(company_id, department_id)
        if count > 0:
            raise ConflictError(
                f"Cannot delete a department with {count} active employee(s) assigned.",
                details={"employee_count": count},
            )
        self.repo.soft_delete(department)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="DEPARTMENT_DELETED",
            entity_type="department",
            entity_id=department.id,
            details={"name": department.name},
        )
        self.db.commit()


# The two fields an "Own" caller may change on their own employee record
# (Spec 10.3 route 23: "employees may edit only contact fields; department,
# level, manager and dates are HR-only"). `email` is treated as the
# administrative work-email field, HR-only alongside those.
CONTACT_FIELDS = {"last_name", "personal_email", "phone"}


def get_policy_notice_days(
    level: str | None, is_probation: bool = False, custom_days: int | None = None
) -> int:
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
        self.location_repo = CompanyLocationRepository(db)
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

    def _validate_location(self, company_id: uuid.UUID, location_id: uuid.UUID | None) -> None:
        if location_id is None:
            return
        loc = self.location_repo.get_by_id(location_id, company_id, for_share=True)
        if loc is None or not loc.is_active:
            raise InvalidReferenceError(
                "The specified location does not exist or is inactive.",
                details={"field": "location_id"},
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
        mgr = self.repo.get_by_id_any_status(manager_id, company_id)
        if mgr is None or not mgr.is_active or mgr.deleted_at is not None:
            raise InvalidReferenceError(
                "The specified reporting manager does not exist or is inactive.",
                details={"field": "reporting_manager_id"},
            )
        # Anti-cycle check: traverse candidate manager's reporting hierarchy upwards
        if self_id is not None:
            curr: Employee | None = mgr
            visited = {self_id}
            while curr and curr.reporting_manager_id:
                if curr.reporting_manager_id in visited:
                    raise InvalidReferenceError(
                        "Setting this manager would create a circular reporting hierarchy.",
                        details={"field": "reporting_manager_id"},
                    )
                visited.add(curr.reporting_manager_id)
                curr = self.repo.get_by_id_any_status(curr.reporting_manager_id, company_id)

    def search_managers(
        self,
        company_id: uuid.UUID,
        *,
        q: str | None = None,
        exclude_id: uuid.UUID | None = None,
        limit: int = 15,
        actor: User | None = None,
    ) -> list[dict]:
        from sqlalchemy import or_, select

        from app.modules.hr.models import Department

        stmt = (
            select(Employee, Department.name.label("dept_name"))
            .outerjoin(Department, Department.id == Employee.department_id)
            .where(
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
        )

        if actor is not None and actor.role == UserRole.manager:
            caller_employee = self.repo.get_by_user_id(actor.company_id, actor.id)
            if caller_employee is not None:
                stmt = stmt.where(Employee.reporting_manager_id == caller_employee.id)
            else:
                return []

        if exclude_id is not None:
            stmt = stmt.where(Employee.id != exclude_id)

        if q:
            term = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Employee.first_name).like(term),
                    func.lower(Employee.last_name).like(term),
                    func.lower(Employee.employee_code).like(term),
                    func.lower(Employee.email).like(term),
                )
            )

        stmt = stmt.order_by(Employee.first_name, Employee.last_name).limit(limit)
        results = self.db.execute(stmt).all()

        out = []
        for emp, dept_name in results:
            out.append(
                {
                    "id": emp.id,
                    "employee_code": emp.employee_code,
                    "first_name": emp.first_name,
                    "last_name": emp.last_name,
                    "email": emp.email,
                    "position": emp.position,
                    "department_name": dept_name,
                }
            )
        return out

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
        role: str | None = None,
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
            role=role,
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
        self._validate_location(company_id, data.location_id)
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
            location_id=data.location_id,
            position=data.position,
            level=data.level,
            reporting_manager_id=data.reporting_manager_id,
            employment_type=data.employment_type,
            hire_date=data.hire_date,
            probation_end_date=data.probation_end_date,
            notice_period_days=get_policy_notice_days(
                level=data.level,
                is_probation=bool(
                    data.probation_end_date and data.probation_end_date > data.hire_date
                ),
                custom_days=data.notice_period_days,
            ),
            is_attendance_exempt=data.is_attendance_exempt,
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
        # Owner, HR Admin, and Super Admin have unrestricted read access to all employee profiles.
        if current_user.role in (UserRole.owner, UserRole.hr_admin, UserRole.super_admin):
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
        is_hr = current_user.role in (UserRole.owner, UserRole.hr_admin)

        # Lock the row for update. Allow inactive for all lookups in the same company,
        # then enforce permission checks below.
        employee = self.repo.get_by_id_for_update(employee_id, company_id, allow_inactive=True)
        if employee is None:
            raise NotFoundError("Employee not found.")

        is_own = employee.user_id == current_user.id
        if not is_hr and not is_own:
            raise ForbiddenError("You do not have permission to update this employee.")

        if not is_hr and is_own and not employee.is_active:
            raise ForbiddenError("You do not have permission to update this employee.")

        updates = data.model_dump(exclude_unset=True)
        if not is_hr:
            restricted = set(updates) - CONTACT_FIELDS
            if restricted:
                raise ForbiddenError(
                    "You may only update your own contact details.",
                    details={"fields": sorted(restricted)},
                )

        # Date sanity check: probation_end_date cannot be before hire_date
        effective_hire_date = updates.get("hire_date") or employee.hire_date
        effective_probation_end_date = (
            updates.get("probation_end_date")
            if "probation_end_date" in updates
            else employee.probation_end_date
        )
        if effective_hire_date and effective_probation_end_date:
            if effective_probation_end_date < effective_hire_date:
                raise ValidationError(
                    "Probation end date cannot be earlier than hire date.",
                    details={"field": "probation_end_date"},
                )

        new_email = updates.get("email")
        email_changed = False
        if new_email and new_email != employee.email:
            email_changed = True
            # Unique ignoring case in employees
            if new_email.lower() != employee.email.lower():
                if self.repo.get_by_email(company_id, new_email):
                    raise ConflictError(
                        "An employee with this email already exists in your company."
                    )
            # Unique ignoring case in users
            existing_user = self.db.scalar(
                select(User).where(
                    User.company_id == company_id,
                    func.lower(User.email) == new_email.lower(),
                )
            )
            if existing_user and (employee.user_id is None or existing_user.id != employee.user_id):
                raise ConflictError("A user with this email already exists in your company.")

        # Links checked only when value changes
        if "department_id" in updates and updates["department_id"] != employee.department_id:
            self._validate_department(company_id, updates["department_id"])
        if "location_id" in updates and updates["location_id"] != employee.location_id:
            self._validate_location(company_id, updates["location_id"])
        if (
            "reporting_manager_id" in updates
            and updates["reporting_manager_id"] != employee.reporting_manager_id
        ):
            self._validate_manager(company_id, updates["reporting_manager_id"], self_id=employee.id)

        # Compute real changes only
        diff: dict[str, dict[str, Any]] = {}
        real_updates: dict[str, Any] = {}
        for field, new_val in updates.items():
            old_val = getattr(employee, field)
            # Compare JSONable representations
            if jsonable(old_val) != jsonable(new_val):
                real_updates[field] = new_val
                # Personal data: audit details mask personal_email and phone with mask_tail
                from_audit = (
                    mask_tail(old_val)
                    if field in ("personal_email", "phone")
                    else jsonable(old_val)
                )
                to_audit = (
                    mask_tail(new_val)
                    if field in ("personal_email", "phone")
                    else jsonable(new_val)
                )
                diff[field] = {"from": from_audit, "to": to_audit}

        # Apply updates if any real changes exist
        if real_updates:
            self.repo.update(employee, **real_updates)

            # If work email changed and employee has a linked user,
            # update users.email and revoke refresh tokens
            if email_changed and employee.user_id is not None:
                linked_user = self.user_repo.get_by_id(employee.user_id, company_id)
                if linked_user is not None:
                    self.user_repo.update(linked_user, company_id, email=new_email)
                    token_repo = RefreshTokenRepository(self.db)
                    active_tokens = token_repo.get_active_by_user(linked_user.id)
                    for token in active_tokens:
                        token_repo.revoke(token)

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

    def clear_department_heads_for_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User | None = None
    ) -> None:
        """Clear head_employee_id from any department headed by this employee
        and write DEPARTMENT_UPDATED audit logs without committing.
        """
        depts = self.db.scalars(
            select(Department).where(
                Department.company_id == company_id,
                Department.head_employee_id == employee_id,
                Department.deleted_at.is_(None),
            )
        ).all()
        for dept in depts:
            self.department_repo.update(dept, head_employee_id=None)
            self.audit.record(
                company_id=company_id,
                actor=actor,
                action="DEPARTMENT_UPDATED",
                entity_type="department",
                entity_id=dept.id,
                details={"head_employee_id": {"from": str(employee_id), "to": None}},
            )

    def deactivate_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User
    ) -> None:
        """Route 24: soft deactivate — never a hard delete (6.5). The row
        stays in the database; `is_active=False` also gates it out of
        `get_by_id`, so it 404s by id afterward. The linked user (if any) is
        deactivated too, so login and refresh both reject it immediately
        (9.2's "reject if is_active is false")."""
        employee = self._get_or_404(company_id, employee_id)
        self.clear_department_heads_for_employee(company_id, employee.id, actor=actor)
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

    def reactivate_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User
    ) -> Employee:
        """Route 25 (`/toggle-active`, spec's literal path name) — reactivate.
        Must look the employee up without the is_active filter, since the
        whole point is finding an already-deactivated row."""
        employee = self.repo.get_by_id_for_update(employee_id, company_id, allow_inactive=True)
        if employee is None:
            raise NotFoundError("Employee not found.")
        if employee.is_active:
            return employee
        self._validate_department(company_id, employee.department_id)
        self._validate_location(company_id, employee.location_id)
        self.repo.update(employee, is_active=True)
        if employee.user_id is not None:
            user = self.user_repo.get_by_id(employee.user_id, company_id)
            if user is not None:
                self.user_repo.update(user, company_id, is_active=True)
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_REACTIVATED",
            entity_type="employee",
            entity_id=employee.id,
            details={"employee_code": employee.employee_code},
        )
        self.db.commit()
        return employee

    def resend_invite(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User
    ) -> tuple[Employee, str]:
        """Route 26: a fresh activation token, on a fresh clock — invalidates
        whatever link was already sent (a new hash overwrites the old one),
        then re-sends via _send_activation_email."""
        employee = self._get_or_404(company_id, employee_id)
        if not employee.is_active:
            raise ConflictError("Cannot resend invite to a deactivated employee.")
        if employee.invitation_status == InvitationStatus.activated:
            raise ConflictError("Employee account is already activated.")
        raw_token = generate_refresh_token()
        self.repo.update(
            employee,
            invitation_status=InvitationStatus.sent,
            activation_token_hash=hash_token(raw_token),
            activation_expires_at=utcnow() + timedelta(days=settings.INVITE_TOKEN_EXPIRE_DAYS),
        )
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_INVITE_RESENT",
            entity_type="employee",
            entity_id=employee.id,
            details={"employee_code": employee.employee_code, "email": employee.email},
        )
        self.db.commit()
        sent_to = self._send_activation_email(company_id, employee, raw_token)
        return employee, sent_to

    # ── Resignation & Full-and-Final (Routes 27-30) ─────────────────
    def submit_resignation(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        data: ResignationSubmitRequest,
        actor: User,
    ) -> Employee:
        if actor.role not in HR_LEVEL_ROLES:
            actor_emp = self.repo.get_by_user_id(company_id, actor.id)
            if actor_emp is None or employee_id != actor_emp.id:
                raise ForbiddenError("You do not have permission to submit this resignation.")

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

    def approve_resignation(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        data: ResignationApproveRequest,
        actor: User,
    ) -> Employee:
        employee = self._get_or_404(company_id, employee_id)
        if employee.user_id == actor.id:
            if actor.role not in (UserRole.owner, UserRole.super_admin):
                msg = "Self-approval is forbidden. You cannot approve your own resignation."
                raise ForbiddenError(msg)

        # Multi-tenant and Role Hierarchy verification
        if actor.role not in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
            # Check if actor is Department Head
            is_dept_head = False
            actor_emp = self.repo.get_by_user_id(company_id, actor.id)
            if actor_emp and employee.department_id:
                dept = self.department_repo.get_by_id(employee.department_id, company_id)
                if dept and dept.head_employee_id == actor_emp.id:
                    is_dept_head = True

            if not is_dept_head:
                from app.core.approval_authority import can_approve_for

                can_approve_for(self.db, actor, employee)

        # State checks:
        # 1. If already approved and actor is hr_admin, owner, or super_admin: allow as amendment
        is_admin_role = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)
        if employee.resignation_status == ResignationStatus.approved and is_admin_role:
            self.repo.update(
                employee,
                resignation_status=ResignationStatus.approved,
                last_working_date=data.last_working_date or employee.last_working_date,
                notice_waived=data.notice_waived,
                notice_recovery_days=data.notice_recovery_days if not data.notice_waived else 0,
            )
            self.db.commit()
            return employee

        # 2. For non-submitted status (including approved for non-admin, rejected, none): 409
        if employee.resignation_status != ResignationStatus.submitted:
            st = employee.resignation_status.value
            raise ConflictError(f"Resignation is not pending decision (current status: {st}).")

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

    def terminate_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, data: TerminationRequest, actor: User
    ) -> Employee:
        employee = self._get_or_404(company_id, employee_id)
        self.clear_department_heads_for_employee(company_id, employee.id, actor=actor)
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
            details={
                "reason": data.reason,
                "termination_date": str(data.termination_date),
                "severance": str(total_severance),
            },
        )
        self.db.commit()
        return employee

    def _calculate_fnf(
        self, company_id: uuid.UUID, employee_id: uuid.UUID
    ) -> FnFSettlementResponse:
        employee = self._get_or_404(company_id, employee_id)
        last_working = employee.last_working_date or utcnow().date()

        # Calculate notice recovery / shortfall
        notice_required = employee.notice_period_days
        notice_served = (
            (last_working - (employee.resignation_date or last_working)).days
            if employee.resignation_date
            else notice_required
        )
        notice_recovery_days = employee.notice_recovery_days if not employee.notice_waived else 0

        # Calculate salary and daily rate from in-force salary assignment or latest payslip
        from app.modules.payroll.payslip_engine import (
            ComponentSpec,
            PayslipInput,
            StatutoryConfigSpec,
            calculate_payslip,
        )
        from app.modules.payroll.repository import (
            EmployeeSalaryRepository,
            PayrollItemRepository,
            SalaryStructureRepository,
            StatutoryConfigRepository,
        )

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
            struct = SalaryStructureRepository(self.db).get_by_id(
                active_sal.structure_id, company_id
            )
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
                        calculation_type=c.calculation_type.value
                        if hasattr(c.calculation_type, "value")
                        else c.calculation_type,
                        value=c.value,
                        percentage_of=c.percentage_of.value
                        if hasattr(c.percentage_of, "value") and c.percentage_of
                        else c.percentage_of,
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
                    financial_year=f"{last_working.year}-{last_working.year + 1}",
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
                    (
                        Decimal(str(e.get("amount", 0)))
                        for e in (latest_slip.earnings_json or [])
                        if e.get("code") == "BASIC"
                    ),
                    None,
                )
                monthly_basic = (
                    basic_in_slip if basic_in_slip is not None else monthly_gross * Decimal("0.40")
                )

        # Daily rate calculation: monthly / 30
        if monthly_gross > Decimal("0.00"):
            per_day_gross = (monthly_gross / Decimal("30")).quantize(Decimal("0.01"))
            per_day_basic = (monthly_basic / Decimal("30")).quantize(Decimal("0.01"))

        notice_recovery_amount = (Decimal(str(notice_recovery_days)) * per_day_gross).quantize(
            Decimal("0.01")
        )

        # Encashable leave balance
        from app.modules.time_leave.repository import LeaveBalanceRepository, LeaveTypeRepository

        leave_type_repo = LeaveTypeRepository(self.db)
        balances = LeaveBalanceRepository(self.db).list_for_employee_year(
            employee.id, last_working.year
        )
        encashable_days = Decimal("0.0")
        for b in balances:
            lt = leave_type_repo.get_by_id(b.leave_type_id, company_id)
            if lt and lt.is_encashable:
                available = b.opening_balance + b.allocated - b.used - b.encashed
                if available > 0:
                    encashable_days += available

        leave_encashment_amount = (encashable_days * per_day_basic).quantize(Decimal("0.01"))
        unpaid_salary_days = last_working.day
        unpaid_salary_amount = (Decimal(str(unpaid_salary_days)) * per_day_gross).quantize(
            Decimal("0.01")
        )

        # Extra FnF components: severance, reimbursements, gratuity, asset deductions
        severance_pay = Decimal(str(employee.severance_pay or 0)).quantize(Decimal("0.01"))
        pending_reimbursements = Decimal(str(employee.pending_reimbursements or 0)).quantize(
            Decimal("0.01")
        )
        gratuity_bonus = Decimal(str(employee.gratuity_bonus or 0)).quantize(Decimal("0.01"))
        asset_deductions = Decimal(str(employee.asset_deductions or 0)).quantize(Decimal("0.01"))

        # Net Formula:
        # FnF Net Payout = (Payable Days Salary + Encashable Leaves + Pending Reimbursements
        #                  + Gratuity/Bonus + Severance)
        #                  - (Notice Shortfall Recovery + Asset Damage/Deductions)
        total_additions = (
            unpaid_salary_amount
            + leave_encashment_amount
            + pending_reimbursements
            + gratuity_bonus
            + severance_pay
        )
        total_deductions = notice_recovery_amount + asset_deductions
        total_settlement = (total_additions - total_deductions).quantize(Decimal("0.01"))

        can_release = bool(
            employee.it_clearance and employee.hr_clearance and employee.finance_clearance
        )

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
            resignation_status=employee.resignation_status.value
            if hasattr(employee.resignation_status, "value")
            else str(employee.resignation_status or "none"),
            is_active=employee.is_active,
            total_settlement_amount=total_settlement,
        )

    def calculate_fnf(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, actor: User
    ) -> FnFSettlementResponse:
        if actor.role not in HR_LEVEL_ROLES:
            raise ForbiddenError("You do not have permission to view full-and-final settlement.")
        return self._calculate_fnf(company_id, employee_id)

    def update_fnf_clearance(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        data: FnFClearanceUpdateRequest,
        actor: User,
    ) -> FnFSettlementResponse:
        employee = self._get_or_404(company_id, employee_id)
        actor_emp = self.repo.get_by_user_id(company_id, actor.id)

        # Disallow an employee/manager from approving their own clearance
        if actor_emp and actor_emp.id == employee.id:
            raise ForbiddenError("You cannot sign off on your own clearance or settlement.")

        is_executive = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)

        # Resolve actor's department clearance function if available
        dept_clearance_function: str | None = None
        if actor_emp and actor_emp.department_id:
            dept = self.department_repo.get_by_id(actor_emp.department_id, company_id)
            if dept:
                dept_clearance_function = dept.clearance_function

        # A manager whose department has no clearance_function cannot access clearance
        if actor.role == UserRole.manager and not dept_clearance_function:
            if data.it_clearance is not None:
                raise ForbiddenError(
                    "Only IT Department Managers or HR Admin/Owner can sign off IT asset clearance."
                )
            if data.hr_clearance is not None:
                raise ForbiddenError(
                    "Only HR Department Managers or HR Admin/Owner can sign off "
                    "HR policy clearance."
                )
            if data.finance_clearance is not None:
                raise ForbiddenError(
                    "Only Finance & Accounts Managers or HR Admin/Owner can sign off "
                    "Finance clearance."
                )
            raise ForbiddenError(
                "Only department managers with a designated clearance function "
                "can access clearance."
            )

        is_it_dept = dept_clearance_function == "it"
        is_fin_dept = dept_clearance_function == "finance"
        is_hr_dept = dept_clearance_function == "hr"

        updates: dict[str, Any] = {}

        # 1. IT Clearance: IT Department leads or HR Admin/Owner
        if data.it_clearance is not None:
            if not (is_executive or (actor.role == UserRole.manager and is_it_dept)):
                raise ForbiddenError(
                    "Only IT Department Managers or HR Admin/Owner can sign off IT asset clearance."
                )
            updates["it_clearance"] = data.it_clearance

        # 2. HR Clearance: HR Department leads or HR Admin/Owner
        if data.hr_clearance is not None:
            if not (is_executive or (actor.role == UserRole.manager and is_hr_dept)):
                raise ForbiddenError(
                    "Only HR Department Managers or HR Admin/Owner can sign off "
                    "HR policy clearance."
                )
            updates["hr_clearance"] = data.hr_clearance

        # 3. Finance Clearance: Finance Department leads or HR Admin/Owner
        if data.finance_clearance is not None:
            if not (is_executive or (actor.role == UserRole.manager and is_fin_dept)):
                raise ForbiddenError(
                    "Only Finance & Accounts Managers or HR Admin/Owner can sign off "
                    "Finance clearance."
                )
            updates["finance_clearance"] = data.finance_clearance

        # 4. Financial Ledger Adjustments: Finance Manager or HR Admin/Owner
        if data.severance_pay is not None:
            if not (is_executive or (actor.role == UserRole.manager and is_fin_dept)):
                raise ForbiddenError(
                    "Only Finance Managers or HR Admin/Owner can adjust severance pay."
                )
            updates["severance_pay"] = data.severance_pay
        if data.pending_reimbursements is not None:
            if not (is_executive or (actor.role == UserRole.manager and is_fin_dept)):
                raise ForbiddenError(
                    "Only Finance Managers or HR Admin/Owner can adjust reimbursements."
                )
            updates["pending_reimbursements"] = data.pending_reimbursements
        if data.gratuity_bonus is not None:
            if not (is_executive or (actor.role == UserRole.manager and is_fin_dept)):
                raise ForbiddenError(
                    "Only Finance Managers or HR Admin/Owner can adjust gratuity/bonus."
                )
            updates["gratuity_bonus"] = data.gratuity_bonus
        if data.asset_deductions is not None:
            if not (
                is_executive or (actor.role == UserRole.manager and (is_fin_dept or is_it_dept))
            ):
                raise ForbiddenError(
                    "Only Finance/IT Managers or HR Admin/Owner can adjust asset deductions."
                )
            updates["asset_deductions"] = data.asset_deductions

        # 5. Maker-Checker Final Settlement Release: strictly Executive (HR Admin & Owner)
        if data.mark_settled:
            if not is_executive:
                raise ForbiddenError(
                    "Maker-Checker Enforcement: Only HR Admin or Company Owner "
                    "can authorize final fund release."
                )
            self.clear_department_heads_for_employee(company_id, employee.id, actor=actor)
            updates["fnf_settled_at"] = utcnow()
            # Ensure employee is marked inactive upon settlement
            updates["is_active"] = False

        if updates:
            self.repo.update(employee, **updates)
            self.db.commit()

        return self._calculate_fnf(company_id, employee_id)


class EmployeeSectionService:
    """Service handling profile sections:
    addresses, emergency-contacts, skills, education, experience.
    """

    VALID_SECTIONS = {"addresses", "emergency-contacts", "skills", "education", "experience"}

    def __init__(self, db: Session):
        self.db = db
        self.repo = EmployeeSectionRepository(db)
        self.emp_repo = EmployeeRepository(db)
        self.audit = AuditService(db)

    def _get_and_check_employee(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        actor: User,
        *,
        is_write: bool = False,
        section: str = "",
        lock_employee: bool = False,
    ) -> Employee:
        if section not in self.VALID_SECTIONS:
            raise NotFoundError(f"Section {section} not found.")

        # If actor's company is different, return 404
        if actor.role != UserRole.super_admin and actor.company_id != company_id:
            raise NotFoundError("Employee not found.")

        # Load employee row (with row lock if requested)
        if lock_employee:
            employee = self.emp_repo.get_by_id_for_update(
                employee_id, company_id, allow_inactive=True
            )
        else:
            employee = self.emp_repo.get_by_id_any_status(employee_id, company_id)

        if not employee:
            raise NotFoundError("Employee not found.")

        is_hr_or_owner = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)
        is_own = employee.user_id is not None and employee.user_id == actor.id

        # Non-HR / non-owner:
        if not is_hr_or_owner:
            # Own record check
            if is_own:
                # Deactivated own record cannot read or write
                if not employee.is_active:
                    raise ForbiddenError(
                        "Deactivated employees cannot view or edit profile sections."
                    )
                return employee

            # If not own record:
            if actor.role == UserRole.manager:
                # Manager writes are ALWAYS forbidden
                if is_write:
                    raise ForbiddenError("Managers cannot modify section entries for reports.")
                # Manager reads: ONLY skills section of a direct report
                if section != "skills":
                    raise ForbiddenError(f"Managers cannot access {section} of direct reports.")
                # Check if employee is a direct report
                mgr_emp = self.emp_repo.get_by_user_id(company_id, actor.id)
                if not mgr_emp or employee.reporting_manager_id != mgr_emp.id:
                    raise ForbiddenError("Employee is not a direct report.")
                return employee

            # Normal employee reading/writing colleague: 403
            raise ForbiddenError("Employees can only view and edit their own profile.")

        return employee

    def list_entries(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, section: str, actor: User
    ) -> list[Any]:
        self._get_and_check_employee(
            company_id, employee_id, actor, is_write=False, section=section
        )
        return self.repo.list_entries(section, employee_id, company_id)

    def create_entry(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        section: str,
        data: dict[str, Any],
        actor: User,
    ) -> Any:
        # Lock employee row to serialize creates and enforce entry cap atomically
        self._get_and_check_employee(
            company_id, employee_id, actor, is_write=True, section=section, lock_employee=True
        )

        # Enforce entry caps
        max_cap = 2 if section == "addresses" else 20
        current_count = self.repo.count_entries(section, employee_id, company_id)
        if current_count >= max_cap:
            raise ConflictError(f"Maximum limit of {max_cap} entries reached for {section}.")

        # Section specific uniqueness checks
        if section == "addresses":
            kind = data.get("kind")
            if kind and self.repo.find_address_by_kind(employee_id, company_id, kind):
                raise ConflictError(f"An address with kind '{kind}' already exists.")
        elif section == "skills":
            name = data.get("name")
            if name and self.repo.find_skill_by_lower_name(employee_id, company_id, name):
                raise ConflictError(f"Skill '{name}' already exists.")

        # Default verification for education/experience
        create_kwargs = dict(data)
        if section in ("education", "experience"):
            create_kwargs["verification_status"] = "unverified"
            create_kwargs["verified_by"] = None
            create_kwargs["verified_at"] = None

        entry = self.repo.create_entry(
            section,
            company_id=company_id,
            employee_id=employee_id,
            **create_kwargs,
        )

        # Audit row
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_ENTRY_CREATED",
            entity_type=section,
            entity_id=employee_id,
            details={"section": section, "entry_id": str(entry.id)},
        )
        self.db.commit()
        return entry

    def update_entry(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        section: str,
        entry_id: uuid.UUID,
        data: dict[str, Any],
        actor: User,
    ) -> Any:
        self._get_and_check_employee(company_id, employee_id, actor, is_write=True, section=section)

        entry = self.repo.get_entry_for_update(
            section, employee_id=employee_id, entry_id=entry_id, company_id=company_id
        )
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found in {section}.")

        is_hr_or_owner = actor.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)

        # Uniqueness checks on update
        if section == "addresses" and "kind" in data and data["kind"] != entry.kind:
            existing_addr = self.repo.find_address_by_kind(employee_id, company_id, data["kind"])
            if existing_addr and existing_addr.id != entry.id:
                raise ConflictError(f"An address with kind '{data['kind']}' already exists.")
        elif (
            section == "skills"
            and "name" in data
            and data["name"].strip().lower() != entry.name.strip().lower()
        ):
            existing_skill = self.repo.find_skill_by_lower_name(
                employee_id, company_id, data["name"]
            )
            if existing_skill and existing_skill.id != entry.id:
                raise ConflictError(f"Skill '{data['name']}' already exists.")

        # Effective date validation for education and experience
        if section in ("education", "experience"):
            from fastapi.exceptions import RequestValidationError

            today_utc = utcnow().date()
            effective_start = data.get("start_date", getattr(entry, "start_date", None))
            effective_end = data.get("end_date", getattr(entry, "end_date", None))

            errors = []
            if (
                "start_date" in data
                and data["start_date"] is not None
                and data["start_date"] > today_utc
            ):
                errors.append(
                    {
                        "type": "value_error",
                        "loc": ("body", "start_date"),
                        "msg": "Date cannot be in the future.",
                        "input": str(data["start_date"]),
                    }
                )
            if "end_date" in data and data["end_date"] is not None and data["end_date"] > today_utc:
                errors.append(
                    {
                        "type": "value_error",
                        "loc": ("body", "end_date"),
                        "msg": "Date cannot be in the future.",
                        "input": str(data["end_date"]),
                    }
                )
            if effective_start and effective_end and effective_end < effective_start:
                bad_loc = "end_date" if "end_date" in data else "start_date"
                errors.append(
                    {
                        "type": "value_error",
                        "loc": ("body", bad_loc),
                        "msg": "end_date cannot be earlier than start_date.",
                        "input": str(data.get(bad_loc)),
                    }
                )

            if errors:
                raise RequestValidationError(errors=errors)

        # Determine real changes
        changed_fields: list[str] = []
        for k, v in data.items():
            if hasattr(entry, k):
                curr = getattr(entry, k)
                if curr != v:
                    changed_fields.append(k)

        if not changed_fields:
            # No-op update: do not write audit log
            return entry

        # Apply updates
        for k in changed_fields:
            setattr(entry, k, data[k])

        # If an employee (non-HR/owner) edits a verified education/experience entry,
        # reset to unverified
        if section in ("education", "experience") and not is_hr_or_owner:
            if entry.verification_status != "unverified":
                entry.verification_status = "unverified"
                entry.verified_by = None
                entry.verified_at = None
                if "verification_status" not in changed_fields:
                    changed_fields.append("verification_status")

        entry.updated_at = utcnow()
        self.db.flush()

        # Audit row
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_ENTRY_UPDATED",
            entity_type=section,
            entity_id=employee_id,
            details={
                "section": section,
                "entry_id": str(entry.id),
                "changed_fields": sorted(changed_fields),
            },
        )
        self.db.commit()
        return entry

    def delete_entry(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        section: str,
        entry_id: uuid.UUID,
        actor: User,
    ) -> None:
        self._get_and_check_employee(company_id, employee_id, actor, is_write=True, section=section)

        entry = self.repo.get_entry_for_update(
            section, employee_id=employee_id, entry_id=entry_id, company_id=company_id
        )
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found in {section}.")

        self.repo.soft_delete_entry(entry)

        self.audit.record(
            company_id=company_id,
            actor=actor,
            action="EMPLOYEE_ENTRY_DELETED",
            entity_type=section,
            entity_id=employee_id,
            details={"section": section, "entry_id": str(entry.id)},
        )
        self.db.commit()

    def set_verification(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        section: str,
        entry_id: uuid.UUID,
        *,
        verified: bool,
        actor: User,
    ) -> Any:
        if section not in ("education", "experience"):
            raise NotFoundError(f"Verification not supported for section {section}.")

        # Strictly HR admin or Owner
        if actor.role not in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin):
            raise ForbiddenError("Only HR admin or owner can verify entries.")

        # Employee check (must belong to same company)
        if actor.role != UserRole.super_admin and actor.company_id != company_id:
            raise NotFoundError("Employee not found.")

        employee = self.emp_repo.get_by_id_any_status(employee_id, company_id)
        if not employee:
            raise NotFoundError("Employee not found.")

        entry = self.repo.get_entry_for_update(
            section, employee_id=employee_id, entry_id=entry_id, company_id=company_id
        )
        if not entry:
            raise NotFoundError(f"Entry {entry_id} not found in {section}.")

        new_status = "verified" if verified else "unverified"
        if entry.verification_status == new_status:
            # Idempotent: no-op, no second audit row
            return entry

        entry.verification_status = new_status
        entry.verified_by = actor.id if verified else None
        entry.verified_at = utcnow() if verified else None
        entry.updated_at = utcnow()
        self.db.flush()

        action = "EMPLOYEE_ENTRY_VERIFIED" if verified else "EMPLOYEE_ENTRY_UNVERIFIED"
        self.audit.record(
            company_id=company_id,
            actor=actor,
            action=action,
            entity_type=section,
            entity_id=employee_id,
            details={"section": section, "entry_id": str(entry.id)},
        )
        self.db.commit()
        return entry
