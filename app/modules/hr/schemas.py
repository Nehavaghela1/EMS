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
    created_at: datetime

    model_config = {"from_attributes": True}


class EmployeeInviteInfo(BaseModel):
    """MVP interim only, same rationale as `CompanyApproveResponse` (WP-05):
    no email backend or Celery queue exists yet (WP-09/WP-26 deliver those).
    The raw activation token is returned once, to the authenticated HR
    caller who triggered it, never logged or stored anywhere in plaintext
    beyond this response. `POST /auth/activate` itself is WP-03's and was
    deliberately skipped this session, so the token cannot be redeemed yet —
    it is generated and safely hashed into storage now so nothing needs
    regenerating once that route exists.
    """

    activation_token: str
    expires_at: datetime


class EmployeeCreateResponse(EmployeeResponse):
    invite: EmployeeInviteInfo
