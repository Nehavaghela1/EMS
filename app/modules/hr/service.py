import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.modules.hr.models import Department
from app.modules.hr.repository import DepartmentRepository
from app.modules.hr.schemas import DepartmentCreateRequest, DepartmentUpdateRequest


class DepartmentService:
    """Routes 31-35 (10.3)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = DepartmentRepository(db)

    def list_departments(
        self, company_id: uuid.UUID, *, q: str | None, sort: str | None, page_params: PageParams
    ) -> tuple[list[Department], int, int]:
        return self.repo.list_departments(
            company_id=company_id, q=q, sort=sort, page_params=page_params
        )

    def create_department(self, company_id: uuid.UUID, data: DepartmentCreateRequest) -> Department:
        if self.repo.get_by_name(company_id, data.name):
            raise ConflictError("A department with this name already exists.")
        department = self.repo.create(
            company_id=company_id, name=data.name, description=data.description
        )
        self.db.commit()
        return department

    def get_department(self, company_id: uuid.UUID, department_id: uuid.UUID) -> Department:
        department = self.repo.get_by_id(department_id, company_id)
        if department is None:
            raise NotFoundError("Department not found.")
        return department

    def update_department(
        self, company_id: uuid.UUID, department_id: uuid.UUID, data: DepartmentUpdateRequest
    ) -> Department:
        department = self.get_department(company_id, department_id)
        updates = data.model_dump(exclude_unset=True)
        new_name = updates.get("name")
        if new_name and new_name.lower() != department.name.lower():
            if self.repo.get_by_name(company_id, new_name):
                raise ConflictError("A department with this name already exists.")
        self.repo.update(department, **updates)
        self.db.commit()
        return department

    def delete_department(self, company_id: uuid.UUID, department_id: uuid.UUID) -> None:
        department = self.get_department(company_id, department_id)
        # TODO(WP-07): block with 409 + the count when any active employee
        # references this department (route 35, 10.3) — `employees` doesn't
        # exist yet, so this delete is currently unconditional.
        self.repo.soft_delete(department)
        self.db.commit()
