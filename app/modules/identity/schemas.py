import uuid
from pydantic import BaseModel, EmailStr
from app.modules.identity.models import UserRole, CompanyStatus


# Company 
class CompanyRegisterRequest(BaseModel):
    company_name: str
    company_email: EmailStr
    admin_email: EmailStr
    admin_password: str
    industry: str | None = None
    phone: str | None = None


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    email: str
    status: CompanyStatus

    model_config = {"from_attributes": True}


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