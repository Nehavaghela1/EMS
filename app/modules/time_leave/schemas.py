import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.modules.time_leave.models import AttendanceStatus


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
