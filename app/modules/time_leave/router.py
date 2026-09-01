import uuid
from datetime import date

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.core.time import utcnow
from app.modules.identity.models import User, UserRole
from app.modules.time_leave.models import (
    Attendance,
    AttendanceStatus,
    EmployeeShift,
    Holiday,
    Leave,
    LeaveStatus,
    LeaveType,
    Shift,
)
from app.modules.time_leave.schemas import (
    AttendanceExportRequest,
    AttendanceRegularizeRequest,
    AttendanceResponse,
    EmployeeShiftResponse,
    HolidayCreateRequest,
    HolidayResponse,
    JobQueuedResponse,
    LeaveApplyRequest,
    LeaveBalanceResponse,
    LeaveDecisionRequest,
    LeaveResponse,
    LeaveTypeCreateRequest,
    LeaveTypeResponse,
    LeaveTypeUpdateRequest,
    ShiftAssignRequest,
    ShiftCreateRequest,
    ShiftResponse,
    ShiftUpdateRequest,
)
from app.modules.time_leave.service import (
    AttendanceService,
    HolidayService,
    LeaveService,
    LeaveTypeService,
    ShiftService,
)

attendance_router = APIRouter(prefix="/attendance", tags=["Attendance"])
shifts_router = APIRouter(prefix="/shifts", tags=["Shifts"])
holidays_router = APIRouter(prefix="/holidays", tags=["Holidays"])
leave_types_router = APIRouter(prefix="/leave-types", tags=["Leave Types"])
leaves_router = APIRouter(prefix="/leaves", tags=["Leaves"])


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


# --- Holidays (routes 55-57) ------------------------------------------------


def _to_holiday_response(holiday: Holiday) -> HolidayResponse:
    return HolidayResponse.model_validate(holiday)


@holidays_router.get("", response_model=list[HolidayResponse])
def list_holidays(
    year: int | None = None,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    target_year = year if year is not None else utcnow().date().year
    holidays = HolidayService(db).list_holidays(user.company_id, target_year)
    return [_to_holiday_response(h) for h in holidays]


@holidays_router.post("", response_model=HolidayResponse, status_code=201)
def create_holiday(
    data: HolidayCreateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    holiday = HolidayService(db).create_holiday(user.company_id, data)
    return _to_holiday_response(holiday)


@holidays_router.delete("/{holiday_id}", status_code=204)
def delete_holiday(
    holiday_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    HolidayService(db).delete_holiday(user.company_id, holiday_id)


# --- Leave types (routes 58-60) ---------------------------------------------


def _to_leave_type_response(leave_type: LeaveType) -> LeaveTypeResponse:
    return LeaveTypeResponse.model_validate(leave_type)


@leave_types_router.get("", response_model=list[LeaveTypeResponse])
def list_leave_types(
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    leave_types = LeaveTypeService(db).list_leave_types(user.company_id)
    return [_to_leave_type_response(lt) for lt in leave_types]


@leave_types_router.post("", response_model=LeaveTypeResponse, status_code=201)
def create_leave_type(
    data: LeaveTypeCreateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    leave_type = LeaveTypeService(db).create_leave_type(user.company_id, data)
    return _to_leave_type_response(leave_type)


@leave_types_router.put("/{leave_type_id}", response_model=LeaveTypeResponse)
def update_leave_type(
    leave_type_id: uuid.UUID,
    data: LeaveTypeUpdateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    leave_type = LeaveTypeService(db).update_leave_type(user.company_id, leave_type_id, data)
    return _to_leave_type_response(leave_type)


# --- Leaves (routes 61-66) --------------------------------------------------


def _to_leave_response(leave: Leave) -> LeaveResponse:
    return LeaveResponse.model_validate(leave)


@leaves_router.get("", response_model=Page[LeaveResponse])
def list_leaves(
    employee_id: uuid.UUID | None = None,
    status: LeaveStatus | None = None,
    leave_type_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    items, total, pages = LeaveService(db).list_leaves(
        user.company_id,
        user,
        employee_id=employee_id,
        status=status,
        leave_type_id=leave_type_id,
        date_from=date_from,
        date_to=date_to,
        page_params=params,
    )
    return Page(
        items=[_to_leave_response(leave) for leave in items],
        page=params.page,
        limit=params.limit,
        total=total,
        pages=pages,
        has_next=params.page < pages,
    )


@leaves_router.post("", response_model=LeaveResponse, status_code=201)
def apply_leave(
    data: LeaveApplyRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    leave = LeaveService(db).apply_leave(user.company_id, data, user)
    return _to_leave_response(leave)


@leaves_router.get("/balance/{employee_id}", response_model=list[LeaveBalanceResponse])
def get_leave_balance(
    employee_id: uuid.UUID,
    year: int | None = None,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    target_year = year if year is not None else utcnow().date().year
    balances = LeaveService(db).get_balance(user.company_id, employee_id, target_year, user)
    return [
        LeaveBalanceResponse(
            leave_type_id=b.leave_type_id,
            leave_type_name=name,
            year=b.year,
            opening_balance=b.opening_balance,
            allocated=b.allocated,
            used=b.used,
            encashed=b.encashed,
            available=b.opening_balance + b.allocated - b.used - b.encashed,
        )
        for b, name in balances
    ]


@leaves_router.get("/{leave_id}", response_model=LeaveResponse)
def get_leave(
    leave_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    leave = LeaveService(db).get_leave(user.company_id, leave_id, user)
    return _to_leave_response(leave)


@leaves_router.put("/{leave_id}", response_model=LeaveResponse)
def decide_leave(
    leave_id: uuid.UUID,
    data: LeaveDecisionRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.manager, UserRole.hr_admin)),
):
    leave = LeaveService(db).decide_leave(user.company_id, leave_id, data, user)
    return _to_leave_response(leave)


@leaves_router.delete("/{leave_id}", response_model=LeaveResponse)
def cancel_leave(
    leave_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return _to_leave_response(LeaveService(db).cancel_leave(user.company_id, leave_id, user))
