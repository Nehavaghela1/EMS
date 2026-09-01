import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate, resolve_sort
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee, EmploymentType


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
        return self.db.scalar(
            select(Department).where(
                Department.company_id == company_id,
                func.lower(Department.name) == name.lower(),
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

    def get_by_id_any_status(
        self, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> Employee | None:
        """Used by DELETE (must find a currently-active row to deactivate —
        the same as get_by_id) and by toggle-active (route 25, must find an
        already-deactivated row to reactivate, so it cannot filter on
        is_active)."""
        return self.db.scalar(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
            )
        )

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

    def get_by_email(self, company_id: uuid.UUID, email: str) -> Employee | None:
        return self.db.scalar(
            select(Employee).where(
                Employee.company_id == company_id,
                func.lower(Employee.email) == email.lower(),
                Employee.deleted_at.is_(None),
            )
        )

    def list_employees(
        self,
        *,
        company_id: uuid.UUID,
        q: str | None,
        department_id: uuid.UUID | None,
        is_active: bool | None,
        level: str | None,
        employment_type: EmploymentType | None,
        reporting_manager_id: uuid.UUID | None,
        sort: str | None,
        page_params: PageParams,
    ) -> tuple[list[Employee], int, int]:
        stmt = select(Employee).where(
            Employee.company_id == company_id, Employee.deleted_at.is_(None)
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
