import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.modules.hr.models import Department
from app.modules.hr.schemas import (
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentUpdateRequest,
)
from app.modules.hr.service import DepartmentService
from app.modules.identity.models import User, UserRole

router = APIRouter(prefix="/departments", tags=["Departments"])


def _to_response(department: Department) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        name=department.name,
        description=department.description,
        head_employee_id=department.head_employee_id,
        employee_count=0,  # real once `employees` exists (WP-07)
        created_at=department.created_at,
    )


@router.get("", response_model=Page[DepartmentResponse])
def list_departments(
    q: str | None = None,
    sort: str | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    items, total, pages = DepartmentService(db).list_departments(
        user.company_id, q=q, sort=sort, page_params=params
    )
    return Page(
        items=[_to_response(d) for d in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@router.post("", response_model=DepartmentResponse, status_code=201)
def create_department(
    data: DepartmentCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    department = DepartmentService(db).create_department(user.company_id, data)
    return _to_response(department)


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    department = DepartmentService(db).get_department(user.company_id, department_id)
    return _to_response(department)


@router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: uuid.UUID,
    data: DepartmentUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    department = DepartmentService(db).update_department(user.company_id, department_id, data)
    return _to_response(department)


@router.delete("/{department_id}", status_code=204)
def delete_department(
    department_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    DepartmentService(db).delete_department(user.company_id, department_id)
