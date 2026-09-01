import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.modules.identity.models import CompanyStatus, UserRole


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
    """MVP interim only: no email backend is wired up yet (WP-26 replaces
    this with a real invite email via Celery + SendGrid). The temporary
    password is returned exactly once, to the authenticated super_admin who
    triggered the approval, and is never logged or stored anywhere.
    """

    company: CompanyResponse
    hr_admin_email: str
    temporary_password: str


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
