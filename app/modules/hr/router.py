import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.modules.hr.models import Department, Employee, EmploymentType
from app.modules.hr.schemas import (
    BulkActionRequest,
    BulkActionResponse,
    ClearanceQueueItemResponse,
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentUpdateRequest,
    EmployeeAddressCreate,
    EmployeeAddressResponse,
    EmployeeAddressUpdate,
    EmployeeCreateRequest,
    EmployeeCreateResponse,
    EmployeeEducationCreate,
    EmployeeEducationResponse,
    EmployeeEducationUpdate,
    EmployeeEmergencyContactCreate,
    EmployeeEmergencyContactResponse,
    EmployeeEmergencyContactUpdate,
    EmployeeExperienceCreate,
    EmployeeExperienceResponse,
    EmployeeExperienceUpdate,
    EmployeeExportJobResponse,
    EmployeeExportRequest,
    EmployeeInviteInfo,
    EmployeeResponse,
    EmployeeSkillCreate,
    EmployeeSkillResponse,
    EmployeeSkillUpdate,
    EmployeeUpdateRequest,
    FnFClearanceUpdateRequest,
    FnFFinanceClearanceResponse,
    FnFHRClearanceResponse,
    FnFITClearanceResponse,
    FnFSettlementResponse,
    ManagerSearchResponse,
    ResignationApproveRequest,
    ResignationSubmitRequest,
    TerminationRequest,
)
from app.modules.hr.service import (
    DepartmentService,
    EmployeeSectionService,
    EmployeeService,
)
from app.modules.identity.models import Company, User, UserRole
from app.modules.platform.service import AuditService
from app.workers.celery_app import celery_app

departments_router = APIRouter(prefix="/departments", tags=["Departments"])
employees_router = APIRouter(prefix="/employees", tags=["Employees"])


def _to_department_response(department: Department, employee_count: int) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        name=department.name,
        description=department.description,
        head_employee_id=department.head_employee_id,
        clearance_function=department.clearance_function,
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
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def create_department(
    request: Request,
    data: DepartmentCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    department, count = DepartmentService(db).create_department(user.company_id, data, actor=user)
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
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_department(
    request: Request,
    department_id: uuid.UUID,
    data: DepartmentUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    department, count = DepartmentService(db).update_department(
        user.company_id, department_id, data, actor=user
    )
    return _to_department_response(department, count)


@departments_router.delete("/{department_id}", status_code=204)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def delete_department(
    request: Request,
    department_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    DepartmentService(db).delete_department(user.company_id, department_id, actor=user)


def _to_employee_response(
    employee: Employee,
    company_map: dict[uuid.UUID, str] | None = None,
    manager: Employee | None = None,
    system_role: str | None = None,
    viewer_user: User | None = None,
) -> EmployeeResponse:
    resp = EmployeeResponse.model_validate(employee)
    if system_role is not None:
        resp.system_role = system_role
    elif hasattr(employee, "system_role") and employee.system_role is not None:
        val = employee.system_role
        resp.system_role = val.value if hasattr(val, "value") else str(val)
    resp.company_id = employee.company_id
    if company_map and employee.company_id in company_map:
        resp.company_name = company_map[employee.company_id]
    if manager:
        resp.manager_name = f"{manager.first_name} {manager.last_name or ''}".strip()
        resp.manager_email = manager.email
        resp.manager_position = manager.position

    # Hide personal_email from non-HR callers (unless viewing self)
    if viewer_user is not None:
        is_hr_or_owner = viewer_user.role in (
            UserRole.hr_admin,
            UserRole.owner,
            UserRole.super_admin,
        )
        is_self = employee.user_id is not None and employee.user_id == viewer_user.id
        if not is_hr_or_owner and not is_self:
            resp.personal_email = None

    return resp


def _to_employee_create_response(employee: Employee, sent_to: str) -> EmployeeCreateResponse:
    # Always set by EmployeeService.create_employee/resend_invite in the same
    # transaction that generated the activation token — never actually None here.
    assert employee.activation_expires_at is not None
    return EmployeeCreateResponse(
        **EmployeeResponse.model_validate(employee).model_dump(),
        invite=EmployeeInviteInfo(sent_to=sent_to, expires_at=employee.activation_expires_at),
    )


@employees_router.get("/managers/search", response_model=list[ManagerSearchResponse])
def search_managers(
    q: str | None = None,
    exclude_id: uuid.UUID | None = None,
    limit: int = 15,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager, UserRole.super_admin)),
):
    """Debounced search for candidate reporting managers."""
    return EmployeeService(db).search_managers(
        user.company_id,
        q=q,
        exclude_id=exclude_id,
        limit=min(limit, 50),
        actor=user,
    )


@employees_router.get("", response_model=Page[EmployeeResponse])
def list_employees(
    q: str | None = None,
    company_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    role: str | None = None,
    system_role: str | None = None,
    is_active: bool | None = None,
    level: str | None = None,
    employment_type: EmploymentType | None = None,
    reporting_manager_id: uuid.UUID | None = None,
    sort: str | None = None,
    params: PageParams = Depends(page_params),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager, UserRole.super_admin)),
):
    target_company_id = company_id if user.role == UserRole.super_admin else user.company_id
    effective_role = role or system_role
    items, total, pages = EmployeeService(db).list_employees(
        target_company_id,
        user,
        q=q,
        department_id=department_id,
        is_active=is_active,
        level=level,
        employment_type=employment_type,
        reporting_manager_id=reporting_manager_id,
        role=effective_role,
        sort=sort,
        page_params=params,
    )

    company_map: dict[uuid.UUID, str] = {}
    user_role_map: dict[uuid.UUID, str] = {}
    if items:
        company_ids = {e.company_id for e in items if e.company_id}
        if company_ids:
            from sqlalchemy import select

            rows = db.execute(
                select(Company.id, Company.name).where(Company.id.in_(company_ids))
            ).all()
            company_map = {r[0]: r[1] for r in rows}

        user_ids = {e.user_id for e in items if e.user_id}
        if user_ids:
            from sqlalchemy import select

            user_rows = db.execute(select(User.id, User.role).where(User.id.in_(user_ids))).all()
            user_role_map = {
                r[0]: (r[1].value if hasattr(r[1], "value") else str(r[1])) for r in user_rows
            }

    return Page(
        items=[
            _to_employee_response(
                e,
                company_map,
                system_role=user_role_map.get(e.user_id) if e.user_id else None,
                viewer_user=user,
            )
            for e in items
        ],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@employees_router.post("", response_model=EmployeeCreateResponse, status_code=201)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def create_employee(
    request: Request,
    data: EmployeeCreateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.super_admin)),
):
    employee, sent_to = EmployeeService(db).create_employee(user.company_id, data, user)
    return _to_employee_create_response(employee, sent_to)


@employees_router.get("/me", response_model=EmployeeResponse)
def get_my_employee(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).get_my_employee_record(user.company_id, user)
    system_role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return _to_employee_response(employee, system_role=system_role)


@employees_router.get("/resignations", response_model=list[EmployeeResponse])
def list_resignations(
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.manager, UserRole.super_admin)),
):
    items, total, pages = EmployeeService(db).list_employees(
        user.company_id,
        user,
        q=None,
        department_id=None,
        is_active=None,
        level=None,
        employment_type=None,
        reporting_manager_id=None,
        sort=None,
        page_params=PageParams(page=1, limit=100),
    )
    return [
        _to_employee_response(e)
        for e in items
        if str(e.resignation_status) not in ("none", "ResignationStatus.none")
    ]


def _build_full_employee_response(
    db: Session, employee: Employee, viewer_user: User | None = None
) -> EmployeeResponse:
    company_map: dict[uuid.UUID, str] = {}
    if employee.company_id:
        company = db.scalar(select(Company).where(Company.id == employee.company_id))
        if company:
            company_map[company.id] = company.name
    manager = None
    if employee.reporting_manager_id:
        manager = db.scalar(
            select(Employee).where(
                Employee.id == employee.reporting_manager_id, Employee.deleted_at.is_(None)
            )
        )
    system_role = None
    if employee.user_id:
        system_role = db.scalar(select(User.role).where(User.id == employee.user_id))
    return _to_employee_response(
        employee, company_map, manager, system_role, viewer_user=viewer_user
    )


# ── Bulk Actions & Export (Spec 2.4) ──────────────────────────


@employees_router.post("/bulk/deactivate", response_model=BulkActionResponse)
@limiter.limit("5/minute", key_func=get_user_or_ip_key)
def bulk_deactivate_employees(
    request: Request,
    data: BulkActionRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    return EmployeeService(db).bulk_deactivate(user.company_id, data.employee_ids, actor=user)


@employees_router.post("/bulk/reactivate", response_model=BulkActionResponse)
@limiter.limit("5/minute", key_func=get_user_or_ip_key)
def bulk_reactivate_employees(
    request: Request,
    data: BulkActionRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    return EmployeeService(db).bulk_reactivate(user.company_id, data.employee_ids, actor=user)


@employees_router.post("/bulk/resend-invite", response_model=BulkActionResponse)
@limiter.limit("5/minute", key_func=get_user_or_ip_key)
def bulk_resend_invite_employees(
    request: Request,
    data: BulkActionRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    return EmployeeService(db).bulk_resend_invite(user.company_id, data.employee_ids, actor=user)


@employees_router.post("/export", response_model=EmployeeExportJobResponse, status_code=202)
@limiter.limit("5/hour", key_func=get_user_or_ip_key)
def export_employees(
    request: Request,
    data: EmployeeExportRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_role(UserRole.hr_admin, UserRole.owner, UserRole.manager, UserRole.super_admin)
    ),
):
    # Record EMPLOYEES_EXPORT_REQUESTED audit row
    AuditService(db).record(
        company_id=user.company_id,
        actor=user,
        action="EMPLOYEES_EXPORT_REQUESTED",
        entity_type="employee",
        entity_id=None,
        details={
            "filters": data.model_dump(exclude_none=True, mode="json"),
        },
    )
    db.commit()

    from app.workers.tasks.hr import export_employees_csv_task

    task = export_employees_csv_task.delay(
        company_id=str(user.company_id),
        actor_id=str(user.id),
        actor_role=user.role.value,
        q=data.q,
        department_id=str(data.department_id) if data.department_id else None,
        is_active=data.is_active,
        level=data.level,
        employment_type=data.employment_type.value if data.employment_type else None,
        reporting_manager_id=str(data.reporting_manager_id) if data.reporting_manager_id else None,
        role=data.role,
        employee_ids=[str(x) for x in data.employee_ids] if data.employee_ids else None,
    )
    return EmployeeExportJobResponse(job_id=task.id)


@employees_router.get("/export/{job_id}/download")
def download_employee_export(
    job_id: str,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_role(UserRole.hr_admin, UserRole.owner, UserRole.manager, UserRole.super_admin)
    ),
):
    async_result = celery_app.AsyncResult(job_id)
    if async_result.state != "SUCCESS":
        raise NotFoundError("Export not found or still processing.")

    result = async_result.result
    if not isinstance(result, dict):
        raise NotFoundError("Export data not found.")

    # Cross-company isolation
    if user.role != UserRole.super_admin and result.get("company_id") != str(user.company_id):
        raise NotFoundError("Export not found.")

    # Authorization: Requester, or HR Admin / Owner of same company
    requester_id = result.get("requester_id")
    is_requester = requester_id and str(user.id) == requester_id
    is_hr_or_owner = user.role in (UserRole.hr_admin, UserRole.owner, UserRole.super_admin)
    if not (is_requester or is_hr_or_owner):
        raise NotFoundError("Export not found.")

    file_path = result.get("file_path")

    # Check expiration (24h)
    expires_at_str = result.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now(UTC) > expires_at:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            raise NotFoundError("Export file has expired.")

    if not file_path or not os.path.exists(file_path):
        raise NotFoundError("Export file not found on disk.")

    file_name = result.get("file_name", "employees.csv")

    # Audit download
    AuditService(db).record(
        company_id=user.company_id,
        actor=user,
        action="EMPLOYEES_EXPORT_DOWNLOADED",
        entity_type="employee",
        entity_id=None,
        details={"job_id": job_id, "file_name": file_name},
    )
    db.commit()

    return FileResponse(
        path=file_path,
        filename=file_name,
        media_type="text/csv",
        headers={"Cache-Control": "no-store"},
    )


@employees_router.get("/clearance-queue", response_model=Page[ClearanceQueueItemResponse])
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def get_clearance_queue(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_role(UserRole.hr_admin, UserRole.manager, UserRole.owner, UserRole.super_admin)
    ),
):
    items, total = EmployeeService(db).list_clearance_queue(
        user.company_id, user, page=page, limit=limit
    )
    pages = (total + limit - 1) // limit if total and limit > 0 else 0
    return Page(
        items=[ClearanceQueueItemResponse.model_validate(i) for i in items],
        page=page,
        limit=limit,
        total=total,
        pages=pages,
        has_next=page < pages,
    )


@employees_router.post("/{employee_id}/reactivate", response_model=EmployeeResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def reactivate_employee(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    employee = EmployeeService(db).reactivate_employee(user.company_id, employee_id, actor=user)
    return _build_full_employee_response(db, employee, viewer_user=user)


@employees_router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).get_employee(user.company_id, employee_id, user)
    return _build_full_employee_response(db, employee, viewer_user=user)


@employees_router.put("/{employee_id}", response_model=EmployeeResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_employee(
    request: Request,
    employee_id: uuid.UUID,
    data: EmployeeUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).update_employee(user.company_id, employee_id, data, user)
    return _build_full_employee_response(db, employee, viewer_user=user)


@employees_router.delete("/{employee_id}", status_code=204)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def deactivate_employee(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    EmployeeService(db).deactivate_employee(user.company_id, employee_id, user)


@employees_router.post(
    "/{employee_id}/toggle-active",
    response_model=EmployeeResponse,
    deprecated=True,
)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def toggle_active_employee(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    employee = EmployeeService(db).reactivate_employee(user.company_id, employee_id, actor=user)
    return _build_full_employee_response(db, employee, viewer_user=user)


@employees_router.post("/{employee_id}/resend-invite", response_model=EmployeeCreateResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def resend_invite(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    employee, sent_to = EmployeeService(db).resend_invite(user.company_id, employee_id, actor=user)
    return _to_employee_create_response(employee, sent_to)


# ── Resignation & Full-and-Final (Routes 27-30) ─────────────────


@employees_router.post("/{employee_id}/resignation", response_model=EmployeeResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def submit_resignation(
    request: Request,
    employee_id: uuid.UUID,
    data: ResignationSubmitRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).submit_resignation(user.company_id, employee_id, data, user)
    return _to_employee_response(employee)


@employees_router.post("/{employee_id}/resignation/withdraw", response_model=EmployeeResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def withdraw_resignation(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    employee = EmployeeService(db).withdraw_resignation(user.company_id, employee_id, user)
    return _to_employee_response(employee)


@employees_router.put("/{employee_id}/resignation/approve", response_model=EmployeeResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def approve_resignation(
    request: Request,
    employee_id: uuid.UUID,
    data: ResignationApproveRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_role(UserRole.hr_admin, UserRole.manager, UserRole.owner, UserRole.super_admin)
    ),
):
    employee = EmployeeService(db).approve_resignation(user.company_id, employee_id, data, user)
    return _to_employee_response(employee)


@employees_router.post("/{employee_id}/terminate", response_model=EmployeeResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def terminate_employee(
    request: Request,
    employee_id: uuid.UUID,
    data: TerminationRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin, UserRole.owner, UserRole.super_admin)),
):
    employee = EmployeeService(db).terminate_employee(user.company_id, employee_id, data, user)
    return _to_employee_response(employee)


FnFRouteResponse = (
    FnFSettlementResponse
    | FnFFinanceClearanceResponse
    | FnFITClearanceResponse
    | FnFHRClearanceResponse
)


@employees_router.get("/{employee_id}/fnf", response_model=FnFRouteResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def get_fnf_settlement(
    request: Request,
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return EmployeeService(db).calculate_fnf(user.company_id, employee_id, user)


@employees_router.put("/{employee_id}/fnf/clearance", response_model=FnFRouteResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_fnf_clearance(
    request: Request,
    employee_id: uuid.UUID,
    data: FnFClearanceUpdateRequest,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(
        require_role(UserRole.hr_admin, UserRole.manager, UserRole.owner, UserRole.super_admin)
    ),
):
    return EmployeeService(db).update_fnf_clearance(user.company_id, employee_id, data, user)


# ---------------------------------------------------------------------------
# Section Routes: addresses, emergency-contacts, skills, education, experience
# ---------------------------------------------------------------------------

SECTION_CREATE_SCHEMAS: dict[str, type[BaseModel]] = {
    "addresses": EmployeeAddressCreate,
    "emergency-contacts": EmployeeEmergencyContactCreate,
    "skills": EmployeeSkillCreate,
    "education": EmployeeEducationCreate,
    "experience": EmployeeExperienceCreate,
}

SECTION_UPDATE_SCHEMAS: dict[str, type[BaseModel]] = {
    "addresses": EmployeeAddressUpdate,
    "emergency-contacts": EmployeeEmergencyContactUpdate,
    "skills": EmployeeSkillUpdate,
    "education": EmployeeEducationUpdate,
    "experience": EmployeeExperienceUpdate,
}

SECTION_RESPONSE_SCHEMAS: dict[str, type[BaseModel]] = {
    "addresses": EmployeeAddressResponse,
    "emergency-contacts": EmployeeEmergencyContactResponse,
    "skills": EmployeeSkillResponse,
    "education": EmployeeEducationResponse,
    "experience": EmployeeExperienceResponse,
}


@employees_router.get("/{employee_id}/{section}")
def list_employee_section_entries(
    employee_id: uuid.UUID,
    section: str,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    entries = EmployeeSectionService(db).list_entries(user.company_id, employee_id, section, user)
    resp_cls = SECTION_RESPONSE_SCHEMAS.get(section)
    if resp_cls:
        return [resp_cls.model_validate(e).model_dump(mode="json") for e in entries]
    return entries


@employees_router.post("/{employee_id}/{section}", status_code=201)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
async def create_employee_section_entry(
    request: Request,
    employee_id: uuid.UUID,
    section: str,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    schema_cls = SECTION_CREATE_SCHEMAS.get(section)
    if not schema_cls:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Section {section} not found.")

    raw_body = await request.json()
    try:
        validated = schema_cls.model_validate(raw_body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    entry = EmployeeSectionService(db).create_entry(
        user.company_id, employee_id, section, validated.model_dump(mode="python"), user
    )
    resp_cls = SECTION_RESPONSE_SCHEMAS[section]
    return resp_cls.model_validate(entry).model_dump(mode="json")


@employees_router.put("/{employee_id}/{section}/{entry_id}")
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
async def update_employee_section_entry(
    request: Request,
    employee_id: uuid.UUID,
    section: str,
    entry_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    schema_cls = SECTION_UPDATE_SCHEMAS.get(section)
    if not schema_cls:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Section {section} not found.")

    raw_body = await request.json()
    try:
        validated = schema_cls.model_validate(raw_body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    # Exclude unset fields so partial updates only change specified keys
    data = validated.model_dump(exclude_unset=True, mode="python")
    entry = EmployeeSectionService(db).update_entry(
        user.company_id, employee_id, section, entry_id, data, user
    )
    resp_cls = SECTION_RESPONSE_SCHEMAS[section]
    return resp_cls.model_validate(entry).model_dump(mode="json")


@employees_router.delete("/{employee_id}/{section}/{entry_id}", status_code=204)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def delete_employee_section_entry(
    request: Request,
    employee_id: uuid.UUID,
    section: str,
    entry_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    EmployeeSectionService(db).delete_entry(user.company_id, employee_id, section, entry_id, user)
    return None


@employees_router.post("/{employee_id}/education/{entry_id}/verify")
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def verify_education_entry(
    request: Request,
    employee_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    entry = EmployeeSectionService(db).set_verification(
        user.company_id, employee_id, "education", entry_id, verified=True, actor=user
    )
    return EmployeeEducationResponse.model_validate(entry).model_dump(mode="json")


@employees_router.post("/{employee_id}/education/{entry_id}/unverify")
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def unverify_education_entry(
    request: Request,
    employee_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    entry = EmployeeSectionService(db).set_verification(
        user.company_id, employee_id, "education", entry_id, verified=False, actor=user
    )
    return EmployeeEducationResponse.model_validate(entry).model_dump(mode="json")


@employees_router.post("/{employee_id}/experience/{entry_id}/verify")
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def verify_experience_entry(
    request: Request,
    employee_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    entry = EmployeeSectionService(db).set_verification(
        user.company_id, employee_id, "experience", entry_id, verified=True, actor=user
    )
    return EmployeeExperienceResponse.model_validate(entry).model_dump(mode="json")


@employees_router.post("/{employee_id}/experience/{entry_id}/unverify")
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def unverify_experience_entry(
    request: Request,
    employee_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    entry = EmployeeSectionService(db).set_verification(
        user.company_id, employee_id, "experience", entry_id, verified=False, actor=user
    )
    return EmployeeExperienceResponse.model_validate(entry).model_dump(mode="json")
