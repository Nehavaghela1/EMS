import datetime as dt
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.time_leave.models import AttendanceStatus, LeaveStatus


class AttendanceRegularizationResponse(BaseModel):
    id: uuid.UUID
    attendance_id: uuid.UUID
    employee_id: uuid.UUID
    manager_id: uuid.UUID | None = None
    requested_check_in: datetime | None = None
    requested_check_out: datetime | None = None
    reason: str
    attachment_url: str | None = None
    admin_notes: str | None = None
    status: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# Attendance (routes 43-49)
class AttendanceResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str | None = None
    employee_code: str | None = None
    department_name: str | None = None
    date: date
    check_in: datetime | None
    check_out: datetime | None
    status: AttendanceStatus
    hours_worked: Decimal | None
    source: str
    notes: str | None
    active_regularization: AttendanceRegularizationResponse | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AttendanceRegularizeRequest(BaseModel):
    """Route 47, HR only. `reason` is required — it and the previous values
    are what go to audit_logs (structurally logged for now; WP-11 delivers
    the real table)."""

    check_in: datetime | None = None
    check_out: datetime | None = None
    status: AttendanceStatus | None = None
    notes: str | None = None
    reason: str


def _as_utc(value: datetime | None) -> datetime | None:
    """A time without a zone is taken as UTC (the server stores UTC only)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


_ReasonStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_OptionalNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None


class AttendanceRegularizationCreate(BaseModel):
    """The attachment is never part of this body: it is a separate file part of the multipart
    request, validated and stored by the server (the client cannot set a link)."""

    model_config = ConfigDict(extra="forbid")

    requested_check_in: datetime | None = None
    requested_check_out: datetime | None = None
    reason: _ReasonStr

    @field_validator("requested_check_in", "requested_check_out")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return _as_utc(value)


class AttendanceRegularizationApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]
    adjusted_check_in: datetime | None = None
    adjusted_check_out: datetime | None = None
    admin_notes: _OptionalNote = None
    rejection_reason: _OptionalNote = None

    @field_validator("adjusted_check_in", "adjusted_check_out")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return _as_utc(value)


class AttendanceExportRequest(BaseModel):
    employee_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: AttendanceStatus | None = None
    department_id: uuid.UUID | None = None


class JobQueuedResponse(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"


# Shifts (routes 50-54)
def _shift_duration_minutes(start: time, end: time) -> int:
    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute
    if end_min <= start_min:
        end_min += 24 * 60
    return end_min - start_min


class ShiftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    start_time: time
    end_time: time
    break_minutes: int = Field(default=60, ge=0, le=240)
    night_allowance: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("99999.99"))

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Shift name cannot be blank")
        if len(trimmed) > 100:
            raise ValueError("Shift name cannot exceed 100 characters")
        return trimmed

    @model_validator(mode="after")
    def _validate_shift_times(self) -> "ShiftCreateRequest":
        if self.start_time == self.end_time:
            raise ValueError("Start and end times must differ")
        duration = _shift_duration_minutes(self.start_time, self.end_time)
        if self.break_minutes >= duration:
            raise ValueError("Break minutes must be shorter than shift duration")
        return self


class ShiftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    start_time: time | None = None
    end_time: time | None = None
    break_minutes: int | None = Field(default=None, ge=0, le=240)
    night_allowance: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("99999.99"))
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Shift name cannot be blank")
        if len(trimmed) > 100:
            raise ValueError("Shift name cannot exceed 100 characters")
        return trimmed

    @model_validator(mode="after")
    def _no_nulls_on_required_fields(self) -> "ShiftUpdateRequest":
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.start_time is not None and self.end_time is not None:
            if self.start_time == self.end_time:
                raise ValueError("Start and end times must differ")
        return self


class ShiftResponse(BaseModel):
    id: uuid.UUID
    name: str
    start_time: time
    end_time: time
    break_minutes: int
    night_allowance: Decimal
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ShiftAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> "ShiftAssignRequest":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be before effective_from")
        return self


class ShiftAssignmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_to: date | None = None


class EmployeeShiftResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    shift_id: uuid.UUID
    effective_from: date
    effective_to: date | None

    model_config = {"from_attributes": True}


class AssignedShiftDetailResponse(BaseModel):
    shift: ShiftResponse
    effective_from: date
    effective_to: date | None = None


# Holidays (routes 55-57)
HOLIDAY_MIN_DATE = date(2000, 1, 1)
HOLIDAY_MAX_DATE = date(2100, 12, 31)


class HolidayCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    date: date
    is_optional: bool = False
    applies_to_department_id: uuid.UUID | None = None

    @field_validator("date")
    @classmethod
    def _date_in_range(cls, value: dt.date) -> dt.date:
        if not HOLIDAY_MIN_DATE <= value <= HOLIDAY_MAX_DATE:
            raise ValueError("date must be between 2000-01-01 and 2100-12-31")
        return value


class HolidayResponse(BaseModel):
    id: uuid.UUID
    name: str
    date: date
    is_optional: bool
    applies_to_department_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class HolidayImportRegionalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str = "IN"
    state: str = "Gujarat"
    year: int = Field(default=2026, ge=2000, le=2100)


class HolidayImportResponse(BaseModel):
    message: str
    imported_count: int
    total_holidays: int
    holidays: list[HolidayResponse]


# Leave types (routes 58-60)
_NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_CodeStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=2, max_length=10, pattern=r"^[A-Za-z0-9]+$"
    ),
]
_DaysDecimal = Annotated[Decimal, Field(ge=0, le=365, allow_inf_nan=False)]
_MaxDays = Annotated[int, Field(ge=1, le=365)]


def _check_half_steps(*values: Decimal | None) -> None:
    for value in values:
        if value is not None and (value * 2) % 1 != 0:
            raise ValueError("must be a multiple of 0.5")


class LeaveTypeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: _NameStr
    code: _CodeStr
    annual_allowance: _DaysDecimal = Decimal("0")
    carry_forward_limit: _DaysDecimal = Decimal("0")
    max_consecutive_days: _MaxDays | None = None
    requires_approval: bool = True
    is_paid: bool = True
    is_encashable: bool = False

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _check_allowances(self) -> "LeaveTypeCreateRequest":
        _check_half_steps(self.annual_allowance, self.carry_forward_limit)
        if self.carry_forward_limit > self.annual_allowance:
            raise ValueError("carry_forward_limit cannot be more than annual_allowance")
        return self


class LeaveTypeUpdateRequest(BaseModel):
    """Only `max_consecutive_days` may be set to null (to clear it); every other
    field is either left out or given a value."""

    model_config = ConfigDict(extra="forbid")

    name: _NameStr | None = None
    code: _CodeStr | None = None
    annual_allowance: _DaysDecimal | None = None
    carry_forward_limit: _DaysDecimal | None = None
    max_consecutive_days: _MaxDays | None = None
    requires_approval: bool | None = None
    is_paid: bool | None = None
    is_encashable: bool | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def _no_nulls_on_required_fields(self) -> "LeaveTypeUpdateRequest":
        for field in self.model_fields_set - {"max_consecutive_days"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        _check_half_steps(self.annual_allowance, self.carry_forward_limit)
        return self


class LeaveTypeResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    annual_allowance: Decimal
    carry_forward_limit: Decimal
    max_consecutive_days: int | None
    requires_approval: bool
    is_paid: bool
    is_encashable: bool
    is_active: bool

    model_config = {"from_attributes": True}


# Leaves (routes 61-66)
class LeaveApplyRequest(BaseModel):
    """Route 62. `employee_id` is optional: omitted for an employee applying
    for themselves; a manager applying for a direct report or HR applying
    for anyone must supply it."""

    model_config = ConfigDict(extra="forbid")

    employee_id: uuid.UUID | None = None
    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    is_half_day: bool = False
    reason: _ReasonStr


class LeaveDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected"]
    rejection_reason: _OptionalNote = None


class LeaveResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    total_days: Decimal
    is_half_day: bool
    reason: str
    status: LeaveStatus
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    rejection_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LeaveBalanceResponse(BaseModel):
    leave_type_id: uuid.UUID
    leave_type_name: str
    year: int
    opening_balance: Decimal
    allocated: Decimal
    used: Decimal
    encashed: Decimal
    available: Decimal


class LeaveSeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: uuid.UUID
    year: int | None = Field(default=None, ge=2000, le=2100)


class CheckInRequest(BaseModel):
    """Optional body for POST /attendance/check-in.  When the frontend
    captures GPS coordinates they are forwarded here; when the browser
    denies access the client may omit them (the backend will check whether
    the employee's assigned location has a geofence configured and raise
    GeolocationPermissionError if it does)."""

    model_config = ConfigDict(extra="forbid")

    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    # `accuracy` is meters of GPS uncertainty reported by the browser;
    # logged to notes for audit, not used in the fence calculation.
    device_accuracy: float | None = Field(default=None, ge=0.0)


class CalendarDayResponse(BaseModel):
    """A single day cell in the attendance calendar matrix."""

    date: date
    day_of_week: int  # 0 = Monday … 6 = Sunday (Python isoweekday - 1)
    status: str  # AttendanceStatus value, or "no_record"
    work_duration_hours: Decimal | None = None
    check_in: datetime | None = None
    check_out: datetime | None = None
    badge_label: str | None = None  # "On Leave", "Diwali", etc.
    holiday_name: str | None = None
    leave_type_name: str | None = None
    is_today: bool = False
    is_future: bool = False


class CalendarResponse(BaseModel):
    employee_id: uuid.UUID
    month: int
    year: int
    days: list[CalendarDayResponse]
    summary: dict[str, int]  # {"present": 18, "absent": 2, …}
