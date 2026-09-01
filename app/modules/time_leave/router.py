import uuid
from datetime import date

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.modules.identity.models import User, UserRole
from app.modules.time_leave.models import Attendance, AttendanceStatus, EmployeeShift, Shift
from app.modules.time_leave.schemas import (
    AttendanceExportRequest,
    AttendanceRegularizeRequest,
    AttendanceResponse,
    EmployeeShiftResponse,
    JobQueuedResponse,
    ShiftAssignRequest,
    ShiftCreateRequest,
    ShiftResponse,
    ShiftUpdateRequest,
)
from app.modules.time_leave.service import AttendanceService, ShiftService

attendance_router = APIRouter(prefix="/attendance", tags=["Attendance"])
shifts_router = APIRouter(prefix="/shifts", tags=["Shifts"])


def _to_attendance_response(record: Attendance) -> AttendanceResponse:
    return AttendanceResponse.model_validate(record)


def _to_shift_response(shift: Shift) -> ShiftResponse:
    return ShiftResponse.model_validate(shift)


def _to_employee_shift_response(assignment: EmployeeShift) -> EmployeeShiftResponse:
    return EmployeeShiftResponse.model_validate(assignment)


@attendance_router.post("/check-in", response_model=AttendanceResponse, status_code=201)
def check_in(
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).check_in(user.company_id, user)
    return _to_attendance_response(record)


@attendance_router.post("/check-out", response_model=AttendanceResponse)
def check_out(
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).check_out(user.company_id, user)
    return _to_attendance_response(record)


@attendance_router.post("/export", response_model=JobQueuedResponse, status_code=202)
def export_attendance(
    data: AttendanceExportRequest,
    db=Depends(get_tenant_db),
    _user: User = Depends(require_role(UserRole.hr_admin)),
):
    job_id = AttendanceService(db).queue_export(_user.company_id, data)
    return JobQueuedResponse(job_id=job_id)


@attendance_router.get("", response_model=Page[AttendanceResponse])
def list_attendance(
    employee_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: AttendanceStatus | None = None,
    department_id: uuid.UUID | None = None,
    params: PageParams = Depends(page_params),
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    items, total, pages = AttendanceService(db).list_attendance(
        user.company_id,
        user,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        department_id=department_id,
        page_params=params,
    )
    return Page(
        items=[_to_attendance_response(r) for r in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@attendance_router.get("/{attendance_id}", response_model=AttendanceResponse)
def get_attendance(
    attendance_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).get_attendance(user.company_id, attendance_id, user)
    return _to_attendance_response(record)


@attendance_router.put("/{attendance_id}", response_model=AttendanceResponse)
def regularize_attendance(
    attendance_id: uuid.UUID,
    data: AttendanceRegularizeRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    record = AttendanceService(db).regularize(user.company_id, attendance_id, data, user)
    return _to_attendance_response(record)


@attendance_router.delete("/{attendance_id}", status_code=204)
def delete_attendance(
    attendance_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    AttendanceService(db).delete_attendance(user.company_id, attendance_id, user)


@shifts_router.get("", response_model=Page[ShiftResponse])
def list_shifts(
    params: PageParams = Depends(page_params),
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    items, total, pages = ShiftService(db).list_shifts(user.company_id, params)
    return Page(
        items=[_to_shift_response(s) for s in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@shifts_router.post("", response_model=ShiftResponse, status_code=201)
def create_shift(
    data: ShiftCreateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    shift = ShiftService(db).create_shift(user.company_id, data)
    return _to_shift_response(shift)


@shifts_router.put("/{shift_id}", response_model=ShiftResponse)
def update_shift(
    shift_id: uuid.UUID,
    data: ShiftUpdateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    shift = ShiftService(db).update_shift(user.company_id, shift_id, data)
    return _to_shift_response(shift)


@shifts_router.delete("/{shift_id}", status_code=204)
def delete_shift(
    shift_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    ShiftService(db).delete_shift(user.company_id, shift_id)


@shifts_router.post("/{shift_id}/assign", response_model=EmployeeShiftResponse, status_code=201)
def assign_shift(
    shift_id: uuid.UUID,
    data: ShiftAssignRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    assignment = ShiftService(db).assign_shift(user.company_id, shift_id, data)
    return _to_employee_shift_response(assignment)
