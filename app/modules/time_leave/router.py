import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.pagination import Page, PageParams, page_params
from app.core.time import utcnow
from app.modules.hr.models import Department, Employee
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
    AssignedShiftDetailResponse,
    AttendanceExportRequest,
    AttendanceRegularizeRequest,
    AttendanceRegularizationCreate,
    AttendanceRegularizationApprove,
    AttendanceRegularizationResponse,
    AttendanceResponse,
    CalendarResponse,
    CheckInRequest,
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


def _to_attendance_response(record: Attendance, db: Session | None = None) -> AttendanceResponse:
    res = AttendanceResponse.model_validate(record)
    if db is not None:
        if record.employee_id:
            emp = db.query(Employee).filter(Employee.id == record.employee_id).first()
            if emp:
                name_parts = [emp.first_name]
                if emp.last_name:
                    name_parts.append(emp.last_name)
                res.employee_name = " ".join(name_parts)
                res.employee_code = emp.employee_code
                if emp.department_id:
                    dept = db.query(Department).filter(Department.id == emp.department_id).first()
                    if dept:
                        res.department_name = dept.name

        # Include latest regularization if pending or recently regularized
        from app.modules.time_leave.repository import AttendanceRepository
        latest_reg = AttendanceRepository(db).get_latest_regularization_for_attendance(record.id, record.company_id)
        if latest_reg:
            res.active_regularization = AttendanceRegularizationResponse.model_validate(latest_reg)

    return res


def _to_shift_response(shift: Shift) -> ShiftResponse:
    return ShiftResponse.model_validate(shift)


def _to_employee_shift_response(assignment: EmployeeShift) -> EmployeeShiftResponse:
    return EmployeeShiftResponse.model_validate(assignment)


@attendance_router.post("/check-in", response_model=AttendanceResponse, status_code=201)
def check_in(
    body: CheckInRequest | None = None,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).check_in(user.company_id, user, body)
    return _to_attendance_response(record, db)


@attendance_router.post("/check-out", response_model=AttendanceResponse)
def check_out(
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).check_out(user.company_id, user)
    return _to_attendance_response(record, db)


@attendance_router.post("/export", response_model=JobQueuedResponse, status_code=202)
def export_attendance(
    data: AttendanceExportRequest,
    db=Depends(get_tenant_db),
    _user: User = Depends(require_role(UserRole.hr_admin)),
):
    job_id = AttendanceService(db).queue_export(_user.company_id, data)
    return JobQueuedResponse(job_id=job_id)


@attendance_router.get("/calendar", response_model=CalendarResponse)
def get_attendance_calendar(
    month: int,
    year: int,
    employee_id: uuid.UUID | None = None,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Normalized month-grid matrix of attendance, holidays, and leaves."""
    return AttendanceService(db).get_calendar(
        user.company_id,
        user,
        employee_id=employee_id,
        month=month,
        year=year,
    )


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
    target_company_id = user.company_id
    if user.role == UserRole.super_admin and employee_id is not None:
        target_emp = db.query(Employee).filter(Employee.id == employee_id).first()
        if target_emp:
            target_company_id = target_emp.company_id

    items, total, pages = AttendanceService(db).list_attendance(
        target_company_id,
        user,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        department_id=department_id,
        page_params=params,
    )
    return Page(
        items=[_to_attendance_response(r, db) for r in items],
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
    return _to_attendance_response(record, db)


@attendance_router.put("/{attendance_id}", response_model=AttendanceResponse)
def regularize_attendance(
    attendance_id: uuid.UUID,
    data: AttendanceRegularizeRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    record = AttendanceService(db).regularize(user.company_id, attendance_id, data, user)
    return _to_attendance_response(record, db)

@attendance_router.get("/{attendance_id}/regularization", response_model=AttendanceRegularizationResponse | None)
def get_attendance_regularization(
    attendance_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    from app.modules.time_leave.repository import AttendanceRepository
    reg = AttendanceRepository(db).get_latest_regularization_for_attendance(attendance_id, user.company_id)
    return reg

@attendance_router.post("/{attendance_id}/regularize", response_model=AttendanceRegularizationResponse)
async def request_regularization(
    attendance_id: uuid.UUID,
    request: Request,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        check_in_str = form.get("check_in") or form.get("requested_check_in")
        check_out_str = form.get("check_out") or form.get("requested_check_out")
        reason = form.get("reason") or ""
        attachment = form.get("attachment")

        from datetime import datetime
        def parse_dt(dt_str):
            if not dt_str:
                return None
            try:
                # Support ISO strings and datetime-local
                return datetime.fromisoformat(str(dt_str))
            except Exception:
                return None

        file_url = None
        if attachment and hasattr(attachment, "filename") and attachment.filename:
            import os, uuid as sys_uuid
            upload_dir = os.path.join(os.getcwd(), "uploads", "regularizations")
            os.makedirs(upload_dir, exist_ok=True)
            safe_name = f"{sys_uuid.uuid4()}_{attachment.filename}"
            storage_path = os.path.join(upload_dir, safe_name)
            content = await attachment.read()
            with open(storage_path, "wb") as f:
                f.write(content)
            # URL accessible via static /files download
            file_url = f"/api/v1/attendance/regularizations/attachments/{safe_name}"

        data = AttendanceRegularizationCreate(
            requested_check_in=parse_dt(check_in_str),
            requested_check_out=parse_dt(check_out_str),
            reason=str(reason),
            attachment_url=file_url,
        )
    else:
        json_body = await request.json()
        data = AttendanceRegularizationCreate.model_validate(json_body)

    record = AttendanceService(db).request_regularization(user.company_id, attendance_id, data, user)
    return record

@attendance_router.get("/regularizations/attachments/{filename}")
def download_regularization_attachment(filename: str):
    import os
    from fastapi.responses import FileResponse
    upload_dir = os.path.join(os.getcwd(), "uploads", "regularizations")
    file_path = os.path.join(upload_dir, filename)
    if not os.path.exists(file_path):
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Attachment not found.")
    return FileResponse(file_path)

@attendance_router.put("/regularizations/{regularization_id}/approve", response_model=AttendanceRegularizationResponse)
def approve_regularization(
    regularization_id: uuid.UUID,
    data: AttendanceRegularizationApprove,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).approve_regularization(user.company_id, regularization_id, data, user)
    return record

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


@shifts_router.get("/assigned/{employee_id}", response_model=AssignedShiftDetailResponse | None)
def get_assigned_shift(
    employee_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    result = ShiftService(db).get_assigned_shift(user.company_id, employee_id)
    if not result:
        return None
    emp_shift, shift = result
    return AssignedShiftDetailResponse(
        shift=_to_shift_response(shift),
        effective_from=emp_shift.effective_from,
        effective_to=emp_shift.effective_to,
    )



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
    target_company_id = user.company_id
    if user.role == UserRole.super_admin and employee_id is not None:
        target_emp = db.query(Employee).filter(Employee.id == employee_id).first()
        if target_emp:
            target_company_id = target_emp.company_id

    items, total, pages = LeaveService(db).list_leaves(
        target_company_id,
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


class LeaveSeedRequest(BaseModel):
    employee_id: uuid.UUID
    year: int | None = None


@leaves_router.post("/balances/seed", response_model=list[LeaveBalanceResponse])
def seed_leave_balances(
    data: LeaveSeedRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    """HR only. Seeds leave balance rows for every active leave type for the given
    employee and year. Safe to call multiple times — skips types already allocated.
    Resolves the 'No balances yet' UX problem for newly onboarded employees.
    """
    from app.core.time import utcnow as _utcnow
    target_year = data.year if data.year is not None else _utcnow().date().year
    results = LeaveService(db).allocate_balances_for_employee(
        user.company_id, data.employee_id, target_year, user
    )
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
        for b, name in results
    ]

