import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr

from app.modules.hr.models import EmploymentType, InvitationStatus


class DepartmentCreateRequest(BaseModel):
    name: str
    description: str | None = None


class DepartmentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    head_employee_id: uuid.UUID | None = None


class DepartmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    head_employee_id: uuid.UUID | None
    employee_count: int
    created_at: datetime


# Employees (Spec 7.3, 10.3 routes 19-26)


class EmployeeCreateRequest(BaseModel):
    """Route 20, HR only. `employee_code` is never client-supplied — it is
    generated server-side under a row lock (11.2)."""

    first_name: str
    last_name: str | None = None
    email: EmailStr
    personal_email: EmailStr | None = None
    phone: str | None = None
    department_id: uuid.UUID | None = None
    position: str | None = None
    level: str | None = None
    reporting_manager_id: uuid.UUID | None = None
    employment_type: EmploymentType = EmploymentType.full_time
    hire_date: date
    probation_end_date: date | None = None
    notice_period_days: int = 30


class EmployeeUpdateRequest(BaseModel):
    """Route 23. One schema for both HR and Own callers — the service
    rejects (403) a non-HR caller who sets anything outside the contact
    fields (`last_name`, `personal_email`, `phone`); department, level,
    manager, dates and employment_type are HR-only (Spec 10.3 route 23).
    """

    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    personal_email: EmailStr | None = None
    phone: str | None = None
    department_id: uuid.UUID | None = None
    position: str | None = None
    level: str | None = None
    reporting_manager_id: uuid.UUID | None = None
    employment_type: EmploymentType | None = None
    hire_date: date | None = None
    probation_end_date: date | None = None
    notice_period_days: int | None = None


class EmployeeResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    employee_code: str
    first_name: str
    last_name: str | None
    email: str
    personal_email: str | None
    phone: str | None
    department_id: uuid.UUID | None
    position: str | None
    level: str | None
    reporting_manager_id: uuid.UUID | None
    employment_type: EmploymentType
    hire_date: date
    probation_end_date: date | None
    notice_period_days: int
    is_active: bool
    invitation_status: InvitationStatus
    resignation_status: str
    resignation_date: date | None = None
    last_working_date: date | None = None
    notice_waived: bool = False
    notice_recovery_days: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class EmployeeInviteInfo(BaseModel):
    """The raw activation token is never returned here (CLAUDE.md rule 10) —
    it goes out by email instead (Spec 13, WP-26). `sent_to` is the address
    it was sent to (the employee's personal email, or their work email if
    no personal one was given), so HR can confirm at a glance where to tell
    the employee to check."""

    sent_to: str
    expires_at: datetime


class EmployeeCreateResponse(EmployeeResponse):
    invite: EmployeeInviteInfo


# Resignation & FnF (Routes 27-30)
class ResignationSubmitRequest(BaseModel):
    resignation_date: date
    last_working_date: date
    reason: str | None = None


class ResignationApproveRequest(BaseModel):
    approved: bool
    last_working_date: date | None = None
    notice_waived: bool = False
    notice_recovery_days: int = 0


class FnFSettlementResponse(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    last_working_date: date
    notice_days_required: int
    notice_days_served: int
    notice_waived: bool
    notice_recovery_days: int
    notice_recovery_amount: float
    encashable_leave_days: float
    leave_encashment_amount: float
    unpaid_salary_days: int
    unpaid_salary_amount: float
    total_settlement_amount: float

