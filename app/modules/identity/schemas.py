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


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# User
class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    company_id: uuid.UUID

    model_config = {"from_attributes": True}