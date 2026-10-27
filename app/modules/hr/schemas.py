import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.core.time import utcnow
from app.modules.hr.models import EmploymentType, InvitationStatus


class DepartmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    head_employee_id: uuid.UUID | None = None
    clearance_function: Literal["it", "finance", "hr"] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not (2 <= len(s) <= 150):
            raise ValueError("Department name must be between 2 and 150 characters.")
        return s


class DepartmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    head_employee_id: uuid.UUID | None = None
    clearance_function: Literal["it", "finance", "hr"] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str:
        if v is None:
            raise ValueError("Department name cannot be null.")
        s = v.strip()
        if not (2 <= len(s) <= 150):
            raise ValueError("Department name must be between 2 and 150 characters.")
        return s


class DepartmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    head_employee_id: uuid.UUID | None
    clearance_function: Literal["it", "finance", "hr"] | None = None
    employee_count: int
    created_at: datetime


# Employees (Spec 7.3, 10.3 routes 19-26)


class EmployeeCreateRequest(BaseModel):
    """Route 20, HR only. `employee_code` is never client-supplied — it is
    generated server-side under a row lock (11.2)."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(..., max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr
    personal_email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    department_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    position: str | None = Field(default=None, max_length=150)
    level: Literal["L1", "L2", "L3"] | None = None
    reporting_manager_id: uuid.UUID | None = None
    employment_type: EmploymentType = EmploymentType.full_time
    hire_date: date
    probation_end_date: date | None = None
    notice_period_days: int = Field(default=30, ge=0, le=365)
    is_attendance_exempt: bool = False

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str) -> str:
        s = v.strip()
        if not (1 <= len(s) <= 100):
            raise ValueError("First name cannot be empty.")
        return s

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("Phone cannot be empty string.")
        return s

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("Position cannot be empty string.")
        return s

    @field_validator("email", mode="before")
    @classmethod
    def validate_and_normalize_email(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v

    @field_validator("personal_email", mode="before")
    @classmethod
    def validate_and_normalize_personal_email(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            v = v.lower()
        return v


class EmployeeUpdateRequest(BaseModel):
    """Route 23. One schema for both HR and Own callers — the service
    rejects (403) a non-HR caller who sets anything outside the contact
    fields (`last_name`, `personal_email`, `phone`); department, level,
    manager, dates and employment_type are HR-only (Spec 10.3 route 23).
    """

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=255)
    personal_email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    department_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    position: str | None = Field(default=None, max_length=150)
    level: Literal["L1", "L2", "L3"] | None = None
    reporting_manager_id: uuid.UUID | None = None
    employment_type: EmploymentType | None = None
    hire_date: date | None = None
    probation_end_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    is_attendance_exempt: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def check_non_empty_and_reject_nulls_on_non_nullable(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if not data:
            raise ValueError("At least one field must be provided for update.")

        non_nullable_fields = {
            "first_name",
            "email",
            "hire_date",
            "employment_type",
            "notice_period_days",
            "is_attendance_exempt",
        }
        for field in non_nullable_fields:
            if field in data and data[field] is None:
                raise ValueError(f"Field '{field}' cannot be null.")

        return data

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not (1 <= len(s) <= 100):
            raise ValueError("First name cannot be empty.")
        return s

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("Last name cannot be empty string.")
        return s

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("Phone cannot be empty string.")
        return s

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("Position cannot be empty string.")
        return s

    @field_validator("email", mode="before")
    @classmethod
    def validate_and_normalize_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip().lower()
        # Validate format using Pydantic's EmailStr adapter
        TypeAdapter(EmailStr).validate_python(v)
        return v

    @field_validator("personal_email", mode="before")
    @classmethod
    def validate_and_normalize_personal_email(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            v = v.lower()
        return v


class EmployeeResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    system_role: str | None = None
    employee_code: str
    first_name: str
    last_name: str | None
    email: str
    personal_email: str | None
    phone: str | None
    department_id: uuid.UUID | None
    location_id: uuid.UUID | None
    department: DepartmentResponse | None = None
    position: str | None
    level: str | None
    reporting_manager_id: uuid.UUID | None
    employment_type: EmploymentType
    hire_date: date
    probation_end_date: date | None
    notice_period_days: int
    is_active: bool
    is_attendance_exempt: bool = False
    invitation_status: InvitationStatus
    resignation_status: str
    resignation_date: date | None = None
    last_working_date: date | None = None
    notice_waived: bool = False
    notice_recovery_days: int = 0
    separation_type: str | None = None
    termination_reason: str | None = None
    severance_pay: Decimal | None = None
    pending_reimbursements: Decimal | None = None
    gratuity_bonus: Decimal | None = None
    asset_deductions: Decimal | None = None
    it_clearance: bool = False
    hr_clearance: bool = False
    finance_clearance: bool = False
    fnf_settled_at: datetime | None = None
    company_id: uuid.UUID | None = None
    company_name: str | None = None
    manager_name: str | None = None
    manager_email: str | None = None
    manager_position: str | None = None
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


class ManagerSearchResponse(BaseModel):
    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str | None
    email: str
    position: str | None = None
    department_name: str | None = None

    model_config = {"from_attributes": True}


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


class TerminationRequest(BaseModel):
    termination_date: date
    reason: str
    severance_pay: Decimal = Decimal("0.00")
    notice_pay_in_lieu: Decimal = Decimal("0.00")
    notes: str | None = None


class FnFClearanceUpdateRequest(BaseModel):
    it_clearance: bool | None = None
    hr_clearance: bool | None = None
    finance_clearance: bool | None = None
    severance_pay: Decimal | None = None
    pending_reimbursements: Decimal | None = None
    gratuity_bonus: Decimal | None = None
    asset_deductions: Decimal | None = None
    mark_settled: bool | None = None


class FnFSettlementResponse(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    last_working_date: date
    separation_type: str | None = "voluntary"
    termination_reason: str | None = None
    notice_days_required: int
    notice_days_served: int
    notice_waived: bool
    notice_recovery_days: int
    notice_recovery_amount: Decimal
    encashable_leave_days: Decimal
    leave_encashment_amount: Decimal
    unpaid_salary_days: int
    unpaid_salary_amount: Decimal
    monthly_gross_salary: Decimal = Decimal("0.00")
    per_day_salary: Decimal = Decimal("0.00")
    severance_pay: Decimal = Decimal("0.00")
    pending_reimbursements: Decimal = Decimal("0.00")
    gratuity_bonus: Decimal = Decimal("0.00")
    asset_deductions: Decimal = Decimal("0.00")
    it_clearance: bool = False
    hr_clearance: bool = False
    finance_clearance: bool = False
    can_release_settlement: bool = False
    fnf_settled_at: datetime | None = None
    resignation_status: str = "none"
    is_active: bool = True
    total_settlement_amount: Decimal


# ---------------------------------------------------------------------------
# Section Schemas: addresses, emergency-contacts, skills, education, experience
# ---------------------------------------------------------------------------


def _strip_str(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip()
        return s
    return v


# 1. Addresses
class EmployeeAddressCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["current", "permanent"]
    line1: str = Field(..., min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(..., min_length=1, max_length=100)

    @field_validator("line1", "line2", "city", "state", "postal_code", "country", mode="before")
    @classmethod
    def strip_and_validate(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("String field cannot be empty.")
            return s
        return v


class EmployeeAddressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["current", "permanent"] | None = None
    line1: str | None = Field(default=None, min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("line1", "line2", "city", "state", "postal_code", "country", mode="before")
    @classmethod
    def strip_and_validate(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null.")
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("String field cannot be empty.")
            return s
        return v

    @model_validator(mode="before")
    @classmethod
    def check_not_empty(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("Update body cannot be empty.")
        return data


class EmployeeAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    company_id: uuid.UUID
    kind: str
    line1: str
    line2: str | None = None
    city: str
    state: str | None = None
    postal_code: str | None = None
    country: str
    created_at: datetime
    updated_at: datetime


# 2. Emergency Contacts
class EmployeeEmergencyContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    relationship: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=1, max_length=30)
    alt_phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None

    @field_validator("name", "relationship", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Text field cannot be empty.")
            return s
        return v

    @field_validator("phone", "alt_phone", mode="before")
    @classmethod
    def validate_phone_field(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Phone cannot be empty.")
            # Allowed characters: digits, +, -, space, (, )
            import re

            if not re.match(r"^[0-9+\-\s()]+$", s) or not re.search(r"\d", s):
                raise ValueError("Invalid phone format.")
            return s
        return v


class EmployeeEmergencyContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    relationship: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    alt_phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None

    @field_validator("name", "relationship", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null.")
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Text field cannot be empty.")
            return s
        return v

    @field_validator("phone", "alt_phone", mode="before")
    @classmethod
    def validate_phone_field(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null.")
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Phone cannot be empty.")
            import re

            if not re.match(r"^[0-9+\-\s()]+$", s) or not re.search(r"\d", s):
                raise ValueError("Invalid phone format.")
            return s
        return v

    @model_validator(mode="before")
    @classmethod
    def check_not_empty(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("Update body cannot be empty.")
        return data


class EmployeeEmergencyContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    company_id: uuid.UUID
    name: str
    relationship: str
    phone: str
    alt_phone: str | None = None
    email: str | None = None
    created_at: datetime
    updated_at: datetime


# 3. Skills
class EmployeeSkillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    level: Literal["beginner", "intermediate", "advanced", "expert"]
    years_experience: int | None = Field(default=None, ge=0, le=60)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Skill name cannot be empty.")
            return s
        return v


class EmployeeSkillUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    level: Literal["beginner", "intermediate", "advanced", "expert"] | None = None
    years_experience: int | None = Field(default=None, ge=0, le=60)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null.")
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Skill name cannot be empty.")
            return s
        return v

    @model_validator(mode="before")
    @classmethod
    def check_not_empty(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("Update body cannot be empty.")
        return data


class EmployeeSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    company_id: uuid.UUID
    name: str
    level: str
    years_experience: int | None = None
    created_at: datetime
    updated_at: datetime


# 4. Education
class EmployeeEducationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str = Field(..., min_length=1, max_length=150)
    degree: str = Field(..., min_length=1, max_length=150)
    field_of_study: str | None = Field(default=None, max_length=150)
    start_date: date
    end_date: date | None = None
    grade: str | None = Field(default=None, max_length=50)

    @field_validator("institution", "degree", "field_of_study", "grade", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be empty.")
            return s
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def check_dates_not_future(cls, v: date | None) -> date | None:
        if v is not None and v > utcnow().date():
            raise ValueError("Date cannot be in the future.")
        return v

    @model_validator(mode="after")
    def check_end_after_start(self) -> "EmployeeEducationCreate":
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        return self


class EmployeeEducationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str | None = Field(default=None, min_length=1, max_length=150)
    degree: str | None = Field(default=None, min_length=1, max_length=150)
    field_of_study: str | None = Field(default=None, max_length=150)
    start_date: date | None = None
    end_date: date | None = None
    grade: str | None = Field(default=None, max_length=50)

    @field_validator("institution", "degree", "field_of_study", "grade", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null.")
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be empty.")
            return s
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def check_dates_not_future(cls, v: date | None) -> date | None:
        if v is not None and v > utcnow().date():
            raise ValueError("Date cannot be in the future.")
        return v

    @model_validator(mode="before")
    @classmethod
    def check_not_empty(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("Update body cannot be empty.")
        return data

    @model_validator(mode="after")
    def check_end_after_start(self) -> "EmployeeEducationUpdate":
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        return self


class EmployeeEducationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    company_id: uuid.UUID
    institution: str
    degree: str
    field_of_study: str | None = None
    start_date: date
    end_date: date | None = None
    grade: str | None = None
    verification_status: str
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# 5. Experience
class EmployeeExperienceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employer: str = Field(..., min_length=1, max_length=150)
    job_title: str = Field(..., min_length=1, max_length=150)
    start_date: date
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("employer", "job_title", "description", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be empty.")
            return s
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def check_dates_not_future(cls, v: date | None) -> date | None:
        if v is not None and v > utcnow().date():
            raise ValueError("Date cannot be in the future.")
        return v

    @model_validator(mode="after")
    def check_end_after_start(self) -> "EmployeeExperienceCreate":
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        return self


class EmployeeExperienceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employer: str | None = Field(default=None, min_length=1, max_length=150)
    job_title: str | None = Field(default=None, min_length=1, max_length=150)
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("employer", "job_title", "description", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Field cannot be null.")
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be empty.")
            return s
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def check_dates_not_future(cls, v: date | None) -> date | None:
        if v is not None and v > utcnow().date():
            raise ValueError("Date cannot be in the future.")
        return v

    @model_validator(mode="before")
    @classmethod
    def check_not_empty(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("Update body cannot be empty.")
        return data

    @model_validator(mode="after")
    def check_end_after_start(self) -> "EmployeeExperienceUpdate":
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        return self


class EmployeeExperienceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    company_id: uuid.UUID
    employer: str
    job_title: str
    start_date: date
    end_date: date | None = None
    description: str | None = None
    verification_status: str
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
