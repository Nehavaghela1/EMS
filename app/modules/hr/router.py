import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.modules.hr.models import Department, Employee, EmploymentType
from app.modules.hr.schemas import (
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentUpdateRequest,
    EmployeeCreateRequest,
    EmployeeCreateResponse,
    EmployeeInviteInfo,
    EmployeeResponse,
    EmployeeUpdateRequest,
)
from app.modules.hr.service import DepartmentService, EmployeeService
from app.modules.identity.models import User, UserRole

departments_router = APIRouter(prefix="/departments", tags=["Departments"])
employees_router = APIRouter(prefix="/employees", tags=["Employees"])


def _to_department_response(department: Department, employee_count: int) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        name=department.name,
        description=department.description,
        head_employee_id=department.head_employee_id,
        employee_count=employee_count,
        created_at=department.created_at,
    )


@departments_router.get("", response_model=Page[DepartmentResponse])
def list_departments(
    q: str | None = None,
    sort: str | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    items, total, pages, counts = DepartmentService(db).list_departments(
        user.company_id, q=q, sort=sort, page_params=params
    )
    return Page(
        items=[_to_department_response(d, counts.get(d.id, 0)) for d in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@departments_router.post("", response_model=DepartmentResponse, status_code=201)
def create_department(
    data: DepartmentCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    department, count = DepartmentService(db).create_department(user.company_id, data)
    return _to_department_response(department, count)


@departments_router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    department, count = DepartmentService(db).get_department(user.company_id, department_id)
    return _to_department_response(department, count)


@departments_router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: uuid.UUID,
    data: DepartmentUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    department, count = DepartmentService(db).update_department(
        user.company_id, department_id, data
    )
    return _to_department_response(department, count)


@departments_router.delete("/{department_id}", status_code=204)
def delete_department(
    department_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    DepartmentService(db).delete_department(user.company_id, department_id)


def _to_employee_response(employee: Employee) -> EmployeeResponse:
    return EmployeeResponse.model_validate(employee)


def _to_employee_create_response(employee: Employee, raw_token: str) -> EmployeeCreateResponse:
    # Always set by EmployeeService.create_employee/resend_invite in the same
    # transaction that generated raw_token — never actually None here.
    assert employee.activation_expires_at is not None
    return EmployeeCreateResponse(
        **EmployeeResponse.model_validate(employee).model_dump(),
        invite=EmployeeInviteInfo(
            activation_token=raw_token, expires_at=employee.activation_expires_at
        ),
    )


@employees_router.get("", response_model=Page[EmployeeResponse])
def list_employees(
    q: str | None = None,
    department_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    level: str | None = None,
    employment_type: EmploymentType | None = None,
    reporting_manager_id: uuid.UUID | None = None,
    sort: str | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager)),
):
    items, total, pages = EmployeeService(db).list_employees(
        user.company_id,
        user,
        q=q,
        department_id=department_id,
        is_active=is_active,
        level=level,
        employment_type=employment_type,
        reporting_manager_id=reporting_manager_id,
        sort=sort,
        page_params=params,
    )
    return Page(
        items=[_to_employee_response(e) for e in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@employees_router.post("", response_model=EmployeeCreateResponse, status_code=201)
def create_employee(
    data: EmployeeCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    employee, raw_token = EmployeeService(db).create_employee(user.company_id, data)
    return _to_employee_create_response(employee, raw_token)


@employees_router.get("/me", response_model=EmployeeResponse)
def get_my_employee(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).get_my_employee_record(user.company_id, user)
    return _to_employee_response(employee)


@employees_router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).get_employee(user.company_id, employee_id, user)
    return _to_employee_response(employee)


@employees_router.put("/{employee_id}", response_model=EmployeeResponse)
def update_employee(
    employee_id: uuid.UUID,
    data: EmployeeUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).update_employee(user.company_id, employee_id, data, user)
    return _to_employee_response(employee)


@employees_router.delete("/{employee_id}", status_code=204)
def deactivate_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    EmployeeService(db).deactivate_employee(user.company_id, employee_id)


@employees_router.post("/{employee_id}/toggle-active", response_model=EmployeeResponse)
def toggle_active_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    employee = EmployeeService(db).reactivate_employee(user.company_id, employee_id)
    return _to_employee_response(employee)


@employees_router.post("/{employee_id}/resend-invite", response_model=EmployeeCreateResponse)
def resend_invite(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    employee, raw_token = EmployeeService(db).resend_invite(user.company_id, employee_id)
    return _to_employee_create_response(employee, raw_token)
