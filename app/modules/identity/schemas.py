import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

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


RESERVED_SUBDOMAINS: frozenset[str] = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "app",
        "auth",
        "billing",
        "cdn",
        "dashboard",
        "dev",
        "docs",
        "ftp",
        "help",
        "imap",
        "login",
        "mail",
        "ns1",
        "ns2",
        "platform",
        "pop",
        "portal",
        "root",
        "smtp",
        "ssh",
        "staging",
        "static",
        "status",
        "support",
        "test",
        "web",
        "webmail",
        "www",
        "sso",
        "oauth",
        "accounts",
        "account",
        "assets",
        "internal",
        "sandbox",
        "prod",
        "production",
        "superadmin",
    }
)


def validate_subdomain_string(v: str | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Subdomain must be text.")
    v = v.strip().lower()
    if not v:
        return None
    if v in RESERVED_SUBDOMAINS:
        raise ValueError("This subdomain is reserved.")
    if len(v) < 3 or len(v) > 63:
        raise ValueError("Subdomain must be between 3 and 63 characters.")
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
        raise ValueError(
            "Subdomain must contain only lowercase letters, digits, and hyphens,"
            " and cannot start or end with a hyphen."
        )
    return v


# Company
class CompanyRegisterRequest(BaseModel):
    """Route 12 — company self-registration. Admin password and workspace
    subdomain can be specified upfront.
    """

    company_name: str
    company_email: EmailStr
    industry: str | None = None
    phone: str | None = None
    country: str = "IN"
    subdomain: str | None = None
    company_size: str | None = None
    password: PasswordStr | None = None

    @field_validator("company_name", mode="before")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Company name must be text.")
        v = v.strip()
        if not v or len(v) < 1 or len(v) > 255:
            raise ValueError("Company name must be between 1 and 255 characters.")
        return v

    @field_validator("company_email", mode="before")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Country must be text.")
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("Country must be a valid 2-letter ISO country code.")
        return v

    @field_validator("subdomain", mode="before")
    @classmethod
    def _validate_subdomain(cls, v: str | None) -> str | None:
        return validate_subdomain_string(v)


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    email: str
    industry: str | None
    country: str
    status: CompanyStatus
    subdomain: str | None = None
    company_size: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    website: str | None = None
    logo_url: str | None = None
    gst_number: str | None = None
    pan_number: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyDetailResponse(CompanyResponse):
    phone: str | None
    rejection_reason: str | None
    approved_at: datetime | None
    counts: dict[str, int]


class CompanyRejectRequest(BaseModel):
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def _validate_reason(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Rejection reason must be text.")
        v = v.strip()
        if not v or len(v) < 1 or len(v) > 500:
            raise ValueError("Rejection reason must be between 1 and 500 characters.")
        return v


class CompanyDeactivateRequest(BaseModel):
    reason: str
    password: str = Field(..., min_length=1, max_length=128)


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
    logo_url: str | None = None


class UserRoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["employee", "manager", "hr_admin", "owner"]
    current_password: str | None = Field(default=None, min_length=1, max_length=128)


class UserRoleUpdateResponse(BaseModel):
    id: uuid.UUID
    role: UserRole
    previous_role: UserRole
    changed: bool

    model_config = ConfigDict(from_attributes=True)


class AdminUserResponse(BaseModel):
    """A slim projection of a User row returned by GET /users/administrators."""

    id: uuid.UUID
    email: str
    role: UserRole
    first_name: str | None = None
    last_name: str | None = None
    employee_id: uuid.UUID | None = None
    position: str | None = None  # Job title / designation from employees table
    hire_date: str | None = None  # ISO date — shown as "Assigned since" in the table

    model_config = {"from_attributes": True}


class AdminCompanyUpdateRequest(CompanyProfileUpdateRequest):
    status: CompanyStatus | None = None
    currency: str | None = None
    country: str | None = None
    gst_number: str | None = None
    pan_number: str | None = None

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Country must be text.")
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("Country must be a valid 2-letter ISO country code.")
        return v


# Auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
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
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: PasswordStr

    @model_validator(mode="after")
    def _validate_new_differs_from_current(self) -> "ChangePasswordRequest":
        if self.new_password == self.current_password:
            raise ValueError("New password must differ from current password.")
        return self


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    company_code: str | None = None


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: PasswordStr
    company_code: str | None = None


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
    company_name: str | None = None
    company_code: str | None = None
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

    @field_validator("username", mode="before")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Username must be text.")
        v = v.strip().lower()
        if len(v) < 3 or len(v) > 30:
            raise ValueError("Username must be between 3 and 30 characters.")

        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            raise ValueError(
                "Username can only contain letters, numbers, dots, hyphens, and underscores."
            )
        return v


# Workspaces
class CreateWorkspaceRequest(BaseModel):
    company_name: str
    company_email: EmailStr | None = None
    subdomain: str | None = None
    country: str = "IN"
    currency: str = "INR"
    seed_departments: bool = True
    seed_shift: bool = True

    @field_validator("company_name", mode="before")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Company name must be text.")
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("Company name must be between 1 and 200 characters.")
        return v

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Country must be text.")
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("Country must be a valid 2-letter ISO country code.")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def _validate_currency(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Currency must be text.")
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError("Currency must be 3 uppercase letters.")
        return v

    @field_validator("subdomain", mode="before")
    @classmethod
    def _validate_subdomain(cls, v: str | None) -> str | None:
        return validate_subdomain_string(v)


class SwitchWorkspaceRequest(BaseModel):
    company_id: uuid.UUID


class UserWorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    role: UserRole
    is_active: bool


class CreateWorkspaceResponse(BaseModel):
    company: CompanyResponse
    access_token: str
    token_type: str = "bearer"


# Locations
class CompanyLocationCreate(BaseModel):
    name: str
    code: str
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    country: str = "IN"
    postal_code: str | None = None
    is_primary: bool = False
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_meters: int = 150
    is_remote_exempt: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not (1 <= len(s) <= 100):
            raise ValueError("Location name must be between 1 and 100 characters.")
        return s

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        s = v.strip().upper()
        if not re.fullmatch(r"^[A-Z0-9-]{2,20}$", s):
            raise ValueError("Location code must be 2 to 20 letters, digits or hyphens.")
        return s

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str) -> str:
        s = v.strip().upper()
        if not re.fullmatch(r"^[A-Z]{2}$", s):
            raise ValueError("Country must be a 2-letter ISO code.")
        return s

    @field_validator("geofence_radius_meters")
    @classmethod
    def validate_radius(cls, v: int) -> int:
        if not (10 <= v <= 5000):
            raise ValueError("Geofence radius must be between 10 and 5000 metres.")
        return v

    @field_validator("address_line1", "city", "state", "postal_code", mode="before")
    @classmethod
    def _validate_address_fields(cls, v: str | None, info) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be text.")
        s = v.strip()
        if not s:
            return None
        max_lens = {
            "address_line1": 255,
            "city": 100,
            "state": 100,
            "postal_code": 20,
        }
        max_l = max_lens.get(info.field_name, 255)
        if len(s) > max_l:
            raise ValueError(f"Field '{info.field_name}' must not exceed {max_l} characters.")
        return s

    @model_validator(mode="after")
    def validate_coordinates(self) -> "CompanyLocationCreate":
        lat = self.latitude
        lon = self.longitude
        if (lat is None and lon is not None) or (lat is not None and lon is None):
            raise ValueError("Latitude and longitude must be given together.")
        if lat is not None:
            if not (-90.0 <= lat <= 90.0):
                raise ValueError("Latitude must be between -90 and 90 degrees.")
        if lon is not None:
            if not (-180.0 <= lon <= 180.0):
                raise ValueError("Longitude must be between -180 and 180 degrees.")
        return self


class CompanyLocationUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None
    is_primary: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_meters: int | None = None
    is_remote_exempt: bool | None = None

    @field_validator(
        "name",
        "code",
        "country",
        "geofence_radius_meters",
        "is_remote_exempt",
        "is_primary",
        mode="wrap",
    )
    @classmethod
    def validate_non_nullable(cls, v, handler, info):
        if v is None:
            raise ValueError(f"Field '{info.field_name}' cannot be null.")
        return handler(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not (1 <= len(s) <= 100):
            raise ValueError("Location name must be between 1 and 100 characters.")
        return s

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        s = v.strip().upper()
        if not re.fullmatch(r"^[A-Z0-9-]{2,20}$", s):
            raise ValueError("Location code must be 2 to 20 letters, digits or hyphens.")
        return s

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str) -> str:
        s = v.strip().upper()
        if not re.fullmatch(r"^[A-Z]{2}$", s):
            raise ValueError("Country must be a 2-letter ISO code.")
        return s

    @field_validator("geofence_radius_meters")
    @classmethod
    def validate_radius(cls, v: int) -> int:
        if not (10 <= v <= 5000):
            raise ValueError("Geofence radius must be between 10 and 5000 metres.")
        return v

    @field_validator("address_line1", "city", "state", "postal_code", mode="before")
    @classmethod
    def _validate_address_fields_update(cls, v: str | None, info) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be text.")
        s = v.strip()
        if not s:
            return None
        max_lens = {
            "address_line1": 255,
            "city": 100,
            "state": 100,
            "postal_code": 20,
        }
        max_l = max_lens.get(info.field_name, 255)
        if len(s) > max_l:
            raise ValueError(f"Field '{info.field_name}' must not exceed {max_l} characters.")
        return s

    @field_validator("latitude")
    @classmethod
    def validate_latitude_range(cls, v: float | None) -> float | None:
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError("Latitude must be between -90 and 90 degrees.")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude_range(cls, v: float | None) -> float | None:
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError("Longitude must be between -180 and 180 degrees.")
        return v


class CompanyLocationResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    code: str
    address_line1: str | None
    city: str | None
    state: str | None
    country: str
    postal_code: str | None
    is_primary: bool
    is_active: bool
    latitude: float | None
    longitude: float | None
    geofence_radius_meters: int
    is_remote_exempt: bool
    created_at: datetime
    updated_at: datetime
