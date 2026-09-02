import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams
from app.core.security import generate_refresh_token, hash_token
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee, EmploymentType, InvitationStatus
from app.modules.hr.repository import DepartmentRepository, EmployeeRepository
from app.modules.hr.schemas import (
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
)
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import CompanyRepository, UserRepository
from app.modules.platform.service import AuditService, DashboardService, jsonable


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


class EmployeeService:
    """Routes 19-26 (10.3), employee_code generation (11.2)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = EmployeeRepository(db)
        self.department_repo = DepartmentRepository(db)
        self.company_repo = CompanyRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    def _get_or_404(self, company_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
        # any-status, not get_by_id: a deactivated employee's row still
        # exists (6.5's soft-delete rule) and HR must still be able to view,
        # edit, or reactivate it — the previous is_active-filtered lookup
        # here 404'd a deactivated employee's own profile route, which is
        # exactly the page the frontend's "Reactivate" button lives on,
        # making that button structurally unreachable. is_active is now
        # visible on the response instead of hidden behind a 404.
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
        company_id: uuid.UUID,
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
        if current_user.role == UserRole.manager:
            caller_employee = self.repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is None:
                return [], 0, 0
            reporting_manager_id = caller_employee.id
        return self.repo.list_employees(
            company_id=company_id,
            q=q,
            department_id=department_id,
            is_active=is_active,
            level=level,
            employment_type=employment_type,
            reporting_manager_id=reporting_manager_id,
            sort=sort,
            page_params=page_params,
        )

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
            notice_period_days=data.notice_period_days,
            # No email backend/Celery queue exists yet (WP-09/WP-26) — the
            # token is handed directly to the HR caller instead, the same
            # MVP substitute WP-05 used for the HR-admin temporary password.
            # That hand-off is the closest available analogue of "sent".
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
        return employee, raw_token

    def get_my_employee_record(self, company_id: uuid.UUID, current_user: User) -> Employee:
        """Route 21."""
        employee = self.repo.get_by_user_id(company_id, current_user.id)
        if employee is None:
            raise NotFoundError("You do not have an employee record.")
        return employee

    def _assert_can_view(
        self, company_id: uuid.UUID, employee: Employee, current_user: User
    ) -> None:
        if current_user.role == UserRole.hr_admin:
            return
        if employee.user_id == current_user.id:
            return
        if current_user.role == UserRole.manager:
            caller_employee = self.repo.get_by_user_id(company_id, current_user.id)
            if caller_employee is not None and employee.reporting_manager_id == caller_employee.id:
                return
        raise ForbiddenError("You do not have permission to view this employee.")

    def get_employee(
        self, company_id: uuid.UUID, employee_id: uuid.UUID, current_user: User
    ) -> Employee:
        """Route 22: Own, Mgr (own reports only), HR."""
        employee = self._get_or_404(company_id, employee_id)
        self._assert_can_view(company_id, employee, current_user)
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
        """Route 26: new activation token, re-queue email (queueing is a
        forward dependency on WP-09's Celery worker — see the invite-token
        note on `create_employee`)."""
        employee = self._get_or_404(company_id, employee_id)
        raw_token = generate_refresh_token()
        self.repo.update(
            employee,
            invitation_status=InvitationStatus.sent,
            activation_token_hash=hash_token(raw_token),
            activation_expires_at=utcnow() + timedelta(days=settings.INVITE_TOKEN_EXPIRE_DAYS),
        )
        self.db.commit()
        return employee, raw_token
