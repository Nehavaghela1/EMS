import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.modules.time_leave.models import AttendanceStatus, LeaveStatus


# Attendance (routes 43-49)
class AttendanceResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    date: date
    check_in: datetime | None
    check_out: datetime | None
    status: AttendanceStatus
    hours_worked: Decimal | None
    source: str
    notes: str | None
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
class ShiftCreateRequest(BaseModel):
    name: str
    start_time: time
    end_time: time
    break_minutes: int = 60
    night_allowance: Decimal = Decimal("0")


class ShiftUpdateRequest(BaseModel):
    name: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    break_minutes: int | None = None
    night_allowance: Decimal | None = None
    is_active: bool | None = None


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
    employee_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None


class EmployeeShiftResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    shift_id: uuid.UUID
    effective_from: date
    effective_to: date | None

    model_config = {"from_attributes": True}


# Holidays (routes 55-57)
class HolidayCreateRequest(BaseModel):
    name: str
    date: date
    is_optional: bool = False
    applies_to_department_id: uuid.UUID | None = None


class HolidayResponse(BaseModel):
    id: uuid.UUID
    name: str
    date: date
    is_optional: bool
    applies_to_department_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# Leave types (routes 58-60)
class LeaveTypeCreateRequest(BaseModel):
    name: str
    code: str
    annual_allowance: Decimal = Decimal("0")
    carry_forward_limit: Decimal = Decimal("0")
    max_consecutive_days: int | None = None
    requires_approval: bool = True
    is_paid: bool = True
    is_encashable: bool = False


class LeaveTypeUpdateRequest(BaseModel):
    name: str | None = None
    annual_allowance: Decimal | None = None
    carry_forward_limit: Decimal | None = None
    max_consecutive_days: int | None = None
    requires_approval: bool | None = None
    is_paid: bool | None = None
    is_encashable: bool | None = None
    is_active: bool | None = None


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

    employee_id: uuid.UUID | None = None
    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    is_half_day: bool = False
    reason: str


class LeaveDecisionRequest(BaseModel):
    status: Literal["approved", "rejected"]
    rejection_reason: str | None = None


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
