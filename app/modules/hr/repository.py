import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate, resolve_sort
from app.core.time import utcnow
from app.modules.hr.models import Department


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
