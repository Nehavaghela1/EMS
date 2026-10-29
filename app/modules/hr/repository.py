import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate, resolve_sort
from app.core.time import utcnow
from app.modules.hr.models import (
    Department,
    Employee,
    EmployeeAddress,
    EmployeeEducation,
    EmployeeEmergencyContact,
    EmployeeExperience,
    EmployeeSkill,
    EmploymentType,
    InvitationStatus,
    ResignationStatus,
)


class DepartmentRepository:
    SORT_COLUMNS = {"name": Department.name, "created_at": Department.created_at}

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, department_id: uuid.UUID, company_id: uuid.UUID) -> Department | None:
        # RLS already scopes this to the caller's tenant — company_id is
        # filtered explicitly too, as the second layer (rule 1, 8.1).
        return self.db.scalar(
            select(Department).where(
                Department.id == department_id,
                Department.company_id == company_id,
                Department.deleted_at.is_(None),
            )
        )

    def get_by_name(self, company_id: uuid.UUID, name: str) -> Department | None:
        trimmed = name.strip() if name else ""
        return self.db.scalar(
            select(Department).where(
                Department.company_id == company_id,
                func.lower(Department.name) == trimmed.lower(),
                Department.deleted_at.is_(None),
            )
        )

    def list_departments(
        self,
        *,
        company_id: uuid.UUID,
        q: str | None,
        sort: str | None,
        page_params: PageParams,
    ) -> tuple[list[Department], int, int]:
        stmt = select(Department).where(
            Department.company_id == company_id, Department.deleted_at.is_(None)
        )
        if q:
            stmt = stmt.where(func.lower(Department.name).like(f"%{q.lower()}%"))
        order = resolve_sort(sort, self.SORT_COLUMNS, default=Department.name.asc())
        stmt = stmt.order_by(order)
        return paginate(self.db, stmt, page_params)

    def count_by_company(self, company_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Department)
                .where(Department.company_id == company_id, Department.deleted_at.is_(None))
            )
            or 0
        )

    def count_active_employees(self, company_id: uuid.UUID, department_id: uuid.UUID) -> int:
        """The 409-blocked-delete check (route 35) and the single-department
        `employee_count` field (route 33/34). Employee and Department share
        this module, so this queries `employees` directly rather than
        reaching across a module boundary.
        """
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Employee)
                .where(
                    Employee.company_id == company_id,
                    Employee.department_id == department_id,
                    Employee.deleted_at.is_(None),
                    Employee.is_active.is_(True),
                )
            )
            or 0
        )

    def employee_counts(
        self, company_id: uuid.UUID, department_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Bulk version of `count_active_employees`, for route 31's list —
        one query for a page of departments instead of N+1."""
        if not department_ids:
            return {}
        stmt = (
            select(Employee.department_id, func.count())
            .where(
                Employee.company_id == company_id,
                Employee.department_id.in_(department_ids),
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
            .group_by(Employee.department_id)
        )
        return {
            department_id: count
            for department_id, count in self.db.execute(stmt).all()
            if department_id is not None
        }

    def create(self, **kwargs) -> Department:
        department = Department(**kwargs)
        self.db.add(department)
        self.db.flush()
        return department

    def update(self, department: Department, **kwargs) -> Department:
        for key, value in kwargs.items():
            setattr(department, key, value)
        self.db.flush()
        return department

    def soft_delete(self, department: Department) -> None:
        department.deleted_at = utcnow()
        self.db.flush()


class EmployeeRepository:
    SORT_COLUMNS = {
        "first_name": Employee.first_name,
        "hire_date": Employee.hire_date,
        "employee_code": Employee.employee_code,
        "created_at": Employee.created_at,
    }

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee | None:
        """The visibility gate for a single-record lookup (routes 21-23, 26):
        a deactivated employee (`is_active = false`) 404s here even though
        the row still exists — the row itself is never hard-deleted.
        """
        return self.db.scalar(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
        )

    def get_by_id_for_update(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, *, allow_inactive: bool = False
    ) -> Employee | None:
        """Lock employee row with SELECT ... FOR UPDATE for atomic mutations."""
        conditions = [
            Employee.id == employee_id,
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
        ]
        if not allow_inactive:
            conditions.append(Employee.is_active.is_(True))
        return self.db.scalar(select(Employee).where(*conditions).with_for_update())

    def get_by_id_any_status(
        self, employee_id: uuid.UUID, company_id: uuid.UUID | None = None
    ) -> Employee | None:
        """Used by DELETE (must find a currently-active row to deactivate —
        the same as get_by_id) and by toggle-active (route 25, must find an
        already-deactivated row to reactivate, so it cannot filter on
        is_active). If company_id is None, finds across all companies (super_admin)."""
        conditions = [
            Employee.id == employee_id,
            Employee.deleted_at.is_(None),
        ]
        if company_id is not None:
            conditions.append(Employee.company_id == company_id)
        return self.db.scalar(select(Employee).where(*conditions))

    def get_by_user_id(self, company_id: uuid.UUID, user_id: uuid.UUID) -> Employee | None:
        """Resolves "this caller's own employee record" (route 21's `/me`,
        and the `Own`/`Mgr` checks on routes 22-23). Spec 9.2 shows an
        `employee_id` JWT claim for this; adding it would mean changing
        AuthService.login/refresh's token-minting contract, which is out of
        scope for this package (see RECONCILIATION spec gaps) — this lookup
        is functionally equivalent, one extra indexed query per request.
        """
        return self.db.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                Employee.user_id == user_id,
                Employee.deleted_at.is_(None),
            )
        )

    def list_direct_report_ids(
        self, company_id: uuid.UUID, manager_employee_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Manager scoping, shared by WP-07's employee list and WP-09/WP-10's
        attendance/leave lists — every "a manager sees only their team"
        route resolves the same set this way."""
        return list(
            self.db.scalars(
                select(Employee.id).where(
                    Employee.company_id == company_id,
                    Employee.reporting_manager_id == manager_employee_id,
                    Employee.deleted_at.is_(None),
                )
            ).all()
        )

    def get_by_email(self, company_id: uuid.UUID, email: str) -> Employee | None:
        return self.db.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                func.lower(Employee.email) == email.lower(),
                Employee.deleted_at.is_(None),
            )
        )

    def get_by_activation_token_hash(self, token_hash: str) -> Employee | None:
        """Public activation preview/redeem (routes 10-11, WP-03) — cross-
        company by necessity, since there is no verified tenant context
        before activation succeeds. `employees` IS RLS-protected (unlike
        `users`/`refresh_tokens`), so the caller must explicitly bind
        `is_platform_admin=True` on the session before calling this — this
        method does not bind context itself, so that intent stays visible
        at the call site (AuthService.preview_activation), not hidden
        inside the repository. Reachable only by possessing the raw,
        unexpired activation token this hash matches — the same class of
        pre-auth exception 7.2 documents for the four `users` lookups.
        """
        return self.db.scalar(
            select(Employee).where(
                Employee.activation_token_hash == token_hash,
                Employee.deleted_at.is_(None),
            )
        )

    def activate(self, employee: Employee, *, user_id: uuid.UUID) -> Employee:
        """Route 11's field-level mutation once the new User exists — the
        token is consumed (cleared) so it can never be redeemed twice."""
        employee.user_id = user_id
        employee.invitation_status = InvitationStatus.activated
        employee.activation_token_hash = None
        employee.activation_expires_at = None
        self.db.flush()
        return employee

    def list_employees(
        self,
        *,
        company_id: uuid.UUID | None = None,
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
        stmt = select(Employee).where(Employee.deleted_at.is_(None))
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        if role and role.strip() and role.strip().lower() != "all":
            from sqlalchemy import String, cast

            from app.modules.identity.models import User

            role_clean = role.strip().lower().replace(" ", "_")
            stmt = stmt.join(User, Employee.user_id == User.id).where(
                func.lower(cast(User.role, String)) == role_clean
            )
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(Employee.first_name).like(pattern)
                | func.lower(func.coalesce(Employee.last_name, "")).like(pattern)
                | func.lower(Employee.email).like(pattern)
                | func.lower(Employee.employee_code).like(pattern)
            )
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
        if is_active is not None:
            stmt = stmt.where(Employee.is_active.is_(is_active))
        if level is not None:
            stmt = stmt.where(Employee.level == level)
        if employment_type is not None:
            stmt = stmt.where(Employee.employment_type == employment_type)
        if reporting_manager_id is not None:
            stmt = stmt.where(Employee.reporting_manager_id == reporting_manager_id)
        order = resolve_sort(sort, self.SORT_COLUMNS, default=Employee.created_at.desc())
        stmt = stmt.order_by(order)
        return paginate(self.db, stmt, page_params)

    def list_for_export(
        self,
        *,
        company_id: uuid.UUID | None = None,
        q: str | None = None,
        department_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        level: str | None = None,
        employment_type: EmploymentType | None = None,
        reporting_manager_id: uuid.UUID | None = None,
        role: str | None = None,
        employee_ids: list[uuid.UUID] | None = None,
        direct_report_ids: list[uuid.UUID] | None = None,
        limit: int = 50000,
    ) -> list[Employee]:
        stmt = select(Employee).where(Employee.deleted_at.is_(None))
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        if direct_report_ids is not None:
            stmt = stmt.where(Employee.id.in_(direct_report_ids))
        if employee_ids is not None and len(employee_ids) > 0:
            stmt = stmt.where(Employee.id.in_(employee_ids))
        if role and role.strip() and role.strip().lower() != "all":
            from sqlalchemy import String, cast

            from app.modules.identity.models import User

            role_clean = role.strip().lower().replace(" ", "_")
            stmt = stmt.join(User, Employee.user_id == User.id).where(
                func.lower(cast(User.role, String)) == role_clean
            )
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(Employee.first_name).like(pattern)
                | func.lower(func.coalesce(Employee.last_name, "")).like(pattern)
                | func.lower(Employee.email).like(pattern)
                | func.lower(Employee.employee_code).like(pattern)
            )
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
        if is_active is not None:
            stmt = stmt.where(Employee.is_active.is_(is_active))
        if level is not None:
            stmt = stmt.where(Employee.level == level)
        if employment_type is not None:
            stmt = stmt.where(Employee.employment_type == employment_type)
        if reporting_manager_id is not None:
            stmt = stmt.where(Employee.reporting_manager_id == reporting_manager_id)
        stmt = stmt.order_by(Employee.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def create(self, **kwargs) -> Employee:
        employee = Employee(**kwargs)
        self.db.add(employee)
        self.db.flush()
        return employee

    def update(self, employee: Employee, **kwargs) -> Employee:
        for key, value in kwargs.items():
            setattr(employee, key, value)
        self.db.flush()
        return employee

    def list_clearance_queue(
        self,
        company_id: uuid.UUID,
        function: str | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[tuple[Employee, str | None]], int]:
        """List employees with approved, unsettled exit whose function clearance is pending.
        Returns tuples of (Employee, department_name) and total count.
        """
        conditions = [
            Employee.company_id == company_id,
            Employee.resignation_status == ResignationStatus.approved,
            Employee.fnf_settled_at.is_(None),
            Employee.deleted_at.is_(None),
        ]
        if function == "it":
            conditions.append(Employee.it_clearance.is_(False))
        elif function == "finance":
            conditions.append(Employee.finance_clearance.is_(False))
        elif function == "hr":
            conditions.append(Employee.hr_clearance.is_(False))
        else:
            conditions.append(
                (Employee.it_clearance.is_(False))
                | (Employee.finance_clearance.is_(False))
                | (Employee.hr_clearance.is_(False))
            )

        total = self.db.scalar(select(func.count(Employee.id)).where(*conditions)) or 0

        stmt = (
            select(Employee, Department.name)
            .outerjoin(Department, Employee.department_id == Department.id)
            .where(*conditions)
            .order_by(Employee.last_working_date.asc().nulls_last(), Employee.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        results = self.db.execute(stmt).all()
        return [(row[0], row[1]) for row in results], total


class EmployeeSectionRepository:
    """Repository for employee profile sections:
    addresses, emergency-contacts, skills, education, experience.
    """

    MODEL_MAP = {
        "addresses": EmployeeAddress,
        "emergency-contacts": EmployeeEmergencyContact,
        "skills": EmployeeSkill,
        "education": EmployeeEducation,
        "experience": EmployeeExperience,
    }

    def __init__(self, db: Session):
        self.db = db

    def get_model(self, section: str):
        model = self.MODEL_MAP.get(section)
        if not model:
            raise ValueError(f"Unknown section: {section}")
        return model

    def list_entries(
        self, section: str, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> list[Any]:
        model = self.get_model(section)
        stmt = (
            select(model)
            .where(
                model.employee_id == employee_id,
                model.company_id == company_id,
                model.deleted_at.is_(None),
            )
            .order_by(model.created_at.asc())
        )
        return list(self.db.scalars(stmt).all())

    def get_entry(
        self, section: str, employee_id: uuid.UUID, entry_id: uuid.UUID, company_id: uuid.UUID
    ) -> Any | None:
        model = self.get_model(section)
        stmt = select(model).where(
            model.id == entry_id,
            model.employee_id == employee_id,
            model.company_id == company_id,
            model.deleted_at.is_(None),
        )
        return self.db.scalar(stmt)

    def get_entry_for_update(
        self, section: str, employee_id: uuid.UUID, entry_id: uuid.UUID, company_id: uuid.UUID
    ) -> Any | None:
        model = self.get_model(section)
        stmt = (
            select(model)
            .where(
                model.id == entry_id,
                model.employee_id == employee_id,
                model.company_id == company_id,
                model.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return self.db.scalar(stmt)

    def count_entries(self, section: str, employee_id: uuid.UUID, company_id: uuid.UUID) -> int:
        model = self.get_model(section)
        stmt = select(func.count(model.id)).where(
            model.employee_id == employee_id,
            model.company_id == company_id,
            model.deleted_at.is_(None),
        )
        return self.db.scalar(stmt) or 0

    def find_address_by_kind(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, kind: str
    ) -> EmployeeAddress | None:
        stmt = select(EmployeeAddress).where(
            EmployeeAddress.employee_id == employee_id,
            EmployeeAddress.company_id == company_id,
            EmployeeAddress.kind == kind,
            EmployeeAddress.deleted_at.is_(None),
        )
        return self.db.scalar(stmt)

    def find_skill_by_lower_name(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, name: str
    ) -> EmployeeSkill | None:
        stmt = select(EmployeeSkill).where(
            EmployeeSkill.employee_id == employee_id,
            EmployeeSkill.company_id == company_id,
            func.lower(EmployeeSkill.name) == func.lower(name.strip()),
            EmployeeSkill.deleted_at.is_(None),
        )
        return self.db.scalar(stmt)

    def create_entry(self, section: str, **kwargs) -> Any:
        model = self.get_model(section)
        entry = model(**kwargs)
        self.db.add(entry)
        self.db.flush()
        return entry

    def update_entry(self, entry: Any, **kwargs) -> Any:
        for k, v in kwargs.items():
            setattr(entry, k, v)
        self.db.flush()
        return entry

    def soft_delete_entry(self, entry: Any) -> None:
        entry.deleted_at = utcnow()
        self.db.flush()
