import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr

from app.core.config import settings
from app.modules.identity.models import CompanyStatus, UserRole


def _validate_password_policy(value: str) -> str:
    """Spec 9.1: minimum length, at least one letter and one digit — no
    maximum below 128, no forbidden characters. Enforced here so it fails
    at the edge with a clear message, shared by every "new password" field
    (change-password, reset-password, activate)."""
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters.")
    if not any(c.isalpha() for c in value):
        raise ValueError("Password must contain at least one letter.")
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one digit.")
    return value


PasswordStr = Annotated[str, AfterValidator(_validate_password_policy)]


# Company
class CompanyRegisterRequest(BaseModel):
    """Route 12 — company self-registration only. No user is created here;
    the HR admin is created at approval time (route 15), per Spec 10.2.
    """

    company_name: str
    company_email: EmailStr
    industry: str | None = None
    phone: str | None = None
    country: str = "IN"


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    email: str
    industry: str | None
    country: str
    status: CompanyStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyDetailResponse(CompanyResponse):
    phone: str | None
    rejection_reason: str | None
    approved_at: datetime | None
    counts: dict[str, int]


class CompanyRejectRequest(BaseModel):
    reason: str


class CompanyApproveResponse(BaseModel):
    """The temporary password is never returned here (CLAUDE.md rule 10) —
    it goes to the new HR admin's own email instead (Spec 13, WP-26)."""

    company: CompanyResponse
    hr_admin_email: str


class CompanyProfileUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    industry: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    website: str | None = None


# Auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    company_code: str | None = None


class TokenResponse(BaseModel):
    # No refresh_token field: the raw refresh token is never a field on a
    # response schema (Spec 5.3, 9.2) — it is set as an httpOnly cookie by the
    # router and never appears in the JSON body.
    access_token: str
    token_type: str = "bearer"


# User
class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    company_id: uuid.UUID

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: PasswordStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: PasswordStr


class UsernameAvailabilityResponse(BaseModel):
    available: bool


class EmployeeSummary(BaseModel):
    """The "linked employee summary" route 5 (`GET /auth/me`) asks for —
    None when the caller has no linked Employee row (e.g. the HR admin
    created directly at company approval, WP-05)."""

    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str | None
    department_id: uuid.UUID | None
    position: str | None

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    """Route 5. `permissions` is a small, deterministic, role-derived
    capability list — the spec defines no dedicated permissions table or
    schema, so this is a documented judgment call (RECONCILIATION spec
    gaps), not a full RBAC engine."""

    id: uuid.UUID
    email: str
    role: UserRole
    company_id: uuid.UUID
    is_active: bool
    must_change_password: bool
    employee: EmployeeSummary | None
    permissions: list[str]


class ActivationPreviewResponse(BaseModel):
    """Route 10: preview an invitation before accepting — name, company,
    expiry, nothing else (no email, no company id — this is public)."""

    first_name: str
    last_name: str | None
    company_name: str
    expires_at: datetime


class ActivateAccountRequest(BaseModel):
    token: str
    username: str
    password: PasswordStr
