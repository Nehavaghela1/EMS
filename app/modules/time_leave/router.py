import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.dependencies import get_current_user, get_tenant_db, require_role
from app.core.exceptions import NotFoundError, ValidationError
from app.core.jobs import authorize_export_job
from app.core.pagination import Page, PageParams, page_params
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.core.time import utcnow
from app.core.upload_validation import MAX_FILE_UPLOAD_BYTES, read_upload_file_capped
from app.modules.hr.models import Department, Employee
from app.modules.identity.models import User, UserRole
from app.modules.platform.service import AuditService
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
    AttendanceRegularizationApprove,
    AttendanceRegularizationCreate,
    AttendanceRegularizationResponse,
    AttendanceRegularizeRequest,
    AttendanceResponse,
    CalendarResponse,
    CheckInRequest,
    EmployeeShiftResponse,
    HolidayCreateRequest,
    HolidayImportRegionalRequest,
    HolidayImportResponse,
    HolidayResponse,
    JobQueuedResponse,
    LeaveApplyRequest,
    LeaveBalanceResponse,
    LeaveDecisionRequest,
    LeaveResponse,
    LeaveSeedRequest,
    LeaveTypeCreateRequest,
    LeaveTypeResponse,
    LeaveTypeUpdateRequest,
    ShiftAssignmentUpdateRequest,
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
from app.workers.celery_app import celery_app

attendance_router = APIRouter(prefix="/attendance", tags=["Attendance"])
shifts_router = APIRouter(prefix="/shifts", tags=["Shifts"])
holidays_router = APIRouter(prefix="/holidays", tags=["Holidays"])
leave_types_router = APIRouter(prefix="/leave-types", tags=["Leave Types"])
leaves_router = APIRouter(prefix="/leaves", tags=["Leaves"])


def get_regularizations_upload_dir() -> str:
    return os.path.join(os.getcwd(), "uploads", "regularizations")


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

        latest_reg = AttendanceRepository(db).get_latest_regularization_for_attendance(
            record.id, record.company_id
        )
        if latest_reg:
            res.active_regularization = AttendanceRegularizationResponse.model_validate(latest_reg)

    return res


def _to_shift_response(shift: Shift) -> ShiftResponse:
    return ShiftResponse.model_validate(shift)


def _to_employee_shift_response(assignment: EmployeeShift) -> EmployeeShiftResponse:
    return EmployeeShiftResponse.model_validate(assignment)


@attendance_router.post("/check-in", response_model=AttendanceResponse, status_code=201)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def check_in(
    request: Request,
    body: CheckInRequest | None = None,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).check_in(user.company_id, user, body)
    return _to_attendance_response(record, db)


@attendance_router.post("/check-out", response_model=AttendanceResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def check_out(
    request: Request,
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
    job_id = AttendanceService(db).queue_export(_user.company_id, data, user_id=_user.id)
    return JobQueuedResponse(job_id=job_id)


@attendance_router.get("/export/{job_id}/download")
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def download_attendance_export(
    job_id: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    authorize_export_job(job_id, user, not_found_message="Export not found.")

    async_result = celery_app.AsyncResult(job_id)
    if async_result.state != "SUCCESS":
        raise NotFoundError("Export not found or still processing.")

    result = async_result.result
    if not isinstance(result, dict):
        raise NotFoundError("Export data not found.")

    file_path = result.get("file_path")
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

    resolved_path = Path(file_path).resolve()
    export_dir_resolved = Path(settings.EXPORT_DIR).resolve()
    if not resolved_path.is_relative_to(export_dir_resolved):
        raise NotFoundError("Export not found.")

    file_name = f"attendance_{datetime.now(UTC).strftime('%Y-%m-%d')}.csv"

    AuditService(db).record(
        company_id=user.company_id,
        actor=user,
        action="ATTENDANCE_EXPORT_DOWNLOADED",
        entity_type="attendance",
        entity_id=None,
        details={"job_id": job_id},
    )
    db.commit()

    return FileResponse(
        path=str(resolved_path),
        filename=file_name,
        media_type="text/csv",
        headers={"Cache-Control": "no-store"},
    )


@attendance_router.get("/calendar", response_model=CalendarResponse)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_attendance_calendar(
    request: Request,
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
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
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def list_attendance(
    request: Request,
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
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_attendance(
    attendance_id: uuid.UUID,
    request: Request,
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


@attendance_router.get(
    "/{attendance_id}/regularization", response_model=AttendanceRegularizationResponse | None
)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_attendance_regularization(
    request: Request,
    attendance_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return AttendanceService(db).get_regularization_for_attendance(
        user.company_id, attendance_id, user
    )


_FORM_ALIASES = {"check_in": "requested_check_in", "check_out": "requested_check_out"}


@attendance_router.post(
    "/{attendance_id}/regularize",
    response_model=AttendanceRegularizationResponse,
    status_code=201,
)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
async def request_regularization(
    attendance_id: uuid.UUID,
    request: Request,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """JSON body, or multipart form with an optional `attachment` file (pdf, png, jpg, jpeg).
    The file is checked and stored under a server-made name; the client never sets a link."""
    attachment: tuple[str, bytes] | None = None
    if "multipart/form-data" in request.headers.get("content-type", ""):
        form = await request.form()
        fields: dict[str, object] = {}
        for key, value in form.multi_items():
            if key == "attachment":
                if isinstance(value, UploadFile) and value.filename:
                    content = await read_upload_file_capped(
                        value, max_bytes=MAX_FILE_UPLOAD_BYTES, request=request
                    )
                    attachment = (value.filename, content)
                continue
            fields[_FORM_ALIASES.get(key, key)] = value
        payload: object = fields
    else:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise ValidationError("The request body is not valid JSON.") from exc
    try:
        data = AttendanceRegularizationCreate.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(
            "The request body failed validation.",
            details={
                "errors": jsonable_encoder(exc.errors(include_url=False, include_context=False))
            },
        ) from exc
    return AttendanceService(db).request_regularization(
        user.company_id,
        attendance_id,
        data,
        user,
        attachment=attachment,
        upload_dir=get_regularizations_upload_dir(),
    )


@attendance_router.get("/regularizations/attachments/{filename}")
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def download_regularization_attachment(
    request: Request,
    filename: str,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """The only way to read an attachment: requester, their approvers and HR-level users."""
    path = AttendanceService(db).resolve_regularization_attachment(
        user.company_id, filename, user, get_regularizations_upload_dir()
    )
    return FileResponse(path)


@attendance_router.put(
    "/regularizations/{regularization_id}/approve", response_model=AttendanceRegularizationResponse
)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def approve_regularization(
    request: Request,
    regularization_id: uuid.UUID,
    data: AttendanceRegularizationApprove,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    record = AttendanceService(db).approve_regularization(
        user.company_id, regularization_id, data, user
    )
    return record


@attendance_router.delete("/{attendance_id}", status_code=204)
def delete_attendance(
    attendance_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    AttendanceService(db).delete_attendance(user.company_id, attendance_id, user)


@shifts_router.get("", response_model=Page[ShiftResponse])
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def list_shifts(
    request: Request,
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
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def create_shift(
    request: Request,
    data: ShiftCreateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    shift = ShiftService(db).create_shift(user.company_id, data, actor=user)
    return _to_shift_response(shift)


@shifts_router.put("/assignments/{assignment_id}", response_model=EmployeeShiftResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_shift_assignment(
    assignment_id: uuid.UUID,
    request: Request,
    data: ShiftAssignmentUpdateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    assignment = ShiftService(db).update_assignment(
        user.company_id, assignment_id, data, actor=user
    )
    return _to_employee_shift_response(assignment)


@shifts_router.put("/{shift_id}", response_model=ShiftResponse)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def update_shift(
    shift_id: uuid.UUID,
    request: Request,
    data: ShiftUpdateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    shift = ShiftService(db).update_shift(user.company_id, shift_id, data, actor=user)
    return _to_shift_response(shift)


@shifts_router.delete("/{shift_id}", status_code=204)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def delete_shift(
    shift_id: uuid.UUID,
    request: Request,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    ShiftService(db).delete_shift(user.company_id, shift_id, actor=user)


@shifts_router.post("/{shift_id}/assign", response_model=EmployeeShiftResponse, status_code=201)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def assign_shift(
    shift_id: uuid.UUID,
    request: Request,
    data: ShiftAssignRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    assignment = ShiftService(db).assign_shift(user.company_id, shift_id, data, actor=user)
    return _to_employee_shift_response(assignment)


@shifts_router.get("/assigned/{employee_id}", response_model=AssignedShiftDetailResponse | None)
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_assigned_shift(
    employee_id: uuid.UUID,
    request: Request,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    result = ShiftService(db).get_assigned_shift(user.company_id, employee_id, actor=user)
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
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def list_holidays(
    request: Request,
    year: int | None = Query(default=None, ge=2000, le=2100),
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    target_year = year if year is not None else utcnow().date().year
    holidays = HolidayService(db).list_holidays(user.company_id, target_year)
    return [_to_holiday_response(h) for h in holidays]


@holidays_router.post("", response_model=HolidayResponse, status_code=201)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def create_holiday(
    request: Request,
    data: HolidayCreateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    holiday = HolidayService(db).create_holiday(user.company_id, data, user)
    return _to_holiday_response(holiday)


@holidays_router.delete("/{holiday_id}", status_code=204)
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def delete_holiday(
    request: Request,
    holiday_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    HolidayService(db).delete_holiday(user.company_id, holiday_id, user)


@holidays_router.get("/regions")
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_supported_holiday_regions(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Returns all supported countries and regional states/territories
    for statutory holiday import.
    """
    return HolidayService.supported_regions()


@holidays_router.get("/regional-preview")
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def preview_regional_holidays(
    request: Request,
    country: str = "IN",
    state: str = "Gujarat",
    year: int = Query(default=2026, ge=2000, le=2100),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Preview of the statutory public holiday list for a country, state and
    year, to look at before importing. The lists come from the project's own
    constants and are not independently verified: HR must confirm them against
    the official notification.
    """
    return HolidayService.preview_regional_holidays(country, state, year)


@holidays_router.post(
    "/import-regional",
    response_model=HolidayImportResponse,
    description=(
        "Owner and HR admin only. Imports the statutory holidays of a country, state and "
        "year as company-wide holidays and skips dates that already exist. The lists come "
        "from the project's own constants and are not independently verified: HR must "
        "confirm them against the official notification before relying on them."
    ),
)
@limiter.limit("5/minute", key_func=get_user_or_ip_key)
def import_regional_holidays(
    request: Request,
    data: HolidayImportRegionalRequest | None = None,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    req_data = data or HolidayImportRegionalRequest()
    imported_count, all_holidays = HolidayService(db).import_regional_holidays(
        company_id=user.company_id,
        actor=user,
        country=req_data.country,
        state=req_data.state,
        year=req_data.year,
    )
    country_name = req_data.country.upper()
    return HolidayImportResponse(
        message=(
            f"Successfully imported {imported_count} statutory holidays for "
            f"{req_data.state} ({country_name}, {req_data.year})."
        ),
        imported_count=imported_count,
        total_holidays=len(all_holidays),
        holidays=[_to_holiday_response(h) for h in all_holidays],
    )


# --- Leave types (routes 58-60) ---------------------------------------------


def _to_leave_type_response(leave_type: LeaveType) -> LeaveTypeResponse:
    return LeaveTypeResponse.model_validate(leave_type)


@leave_types_router.get("", response_model=list[LeaveTypeResponse])
def list_leave_types(
    include_inactive: bool = False,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    leave_types = LeaveTypeService(db).list_leave_types(user.company_id, user, include_inactive)
    return [_to_leave_type_response(lt) for lt in leave_types]


@leave_types_router.post("", response_model=LeaveTypeResponse, status_code=201)
def create_leave_type(
    data: LeaveTypeCreateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    leave_type = LeaveTypeService(db).create_leave_type(user.company_id, data, user)
    return _to_leave_type_response(leave_type)


@leave_types_router.put("/{leave_type_id}", response_model=LeaveTypeResponse)
def update_leave_type(
    leave_type_id: uuid.UUID,
    data: LeaveTypeUpdateRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    leave_type = LeaveTypeService(db).update_leave_type(user.company_id, leave_type_id, data, user)
    return _to_leave_type_response(leave_type)


# --- Leaves (routes 61-66) --------------------------------------------------


def _to_leave_response(leave: Leave) -> LeaveResponse:
    return LeaveResponse.model_validate(leave)


@leaves_router.get("", response_model=Page[LeaveResponse])
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def list_leaves(
    request: Request,
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
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def apply_leave(
    request: Request,
    data: LeaveApplyRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    leave = LeaveService(db).apply_leave(user.company_id, data, user)
    return _to_leave_response(leave)


@leaves_router.get("/balance/{employee_id}", response_model=list[LeaveBalanceResponse])
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_leave_balance(
    request: Request,
    employee_id: uuid.UUID,
    year: int | None = Query(default=None, ge=2000, le=2100),
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    balances = LeaveService(db).get_balance(user.company_id, employee_id, year, user)
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
@limiter.limit("60/minute", key_func=get_user_or_ip_key)
def get_leave(
    request: Request,
    leave_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    leave = LeaveService(db).get_leave(user.company_id, leave_id, user)
    return _to_leave_response(leave)


@leaves_router.put("/{leave_id}", response_model=LeaveResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def decide_leave(
    request: Request,
    leave_id: uuid.UUID,
    data: LeaveDecisionRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Who may decide is the service's approval authority (reporting chain, HR admin,
    owner); anyone else gets the same refusal."""
    leave = LeaveService(db).decide_leave(user.company_id, leave_id, data, user)
    return _to_leave_response(leave)


@leaves_router.delete("/{leave_id}", response_model=LeaveResponse)
@limiter.limit("10/minute", key_func=get_user_or_ip_key)
def cancel_leave(
    request: Request,
    leave_id: uuid.UUID,
    db=Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    return _to_leave_response(LeaveService(db).cancel_leave(user.company_id, leave_id, user))


@leaves_router.post("/balances/seed", response_model=list[LeaveBalanceResponse])
@limiter.limit("30/minute", key_func=get_user_or_ip_key)
def seed_leave_balances(
    request: Request,
    data: LeaveSeedRequest,
    db=Depends(get_tenant_db),
    user: User = Depends(require_role(UserRole.hr_admin)),
):
    """HR only. Seeds leave balance rows for every active leave type for the given
    employee and year (default: the current leave year). Safe to call multiple
    times — skips types already allocated.
    """
    results = LeaveService(db).allocate_balances_for_employee(
        user.company_id, data.employee_id, data.year, user
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
