import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_refresh_token,
    hash_token,
)
from app.modules.identity.models import UserRole, CompanyStatus
from app.modules.identity.repository import (
    CompanyRepository,
    UserRepository,
    RefreshTokenRepository,
)
from app.modules.identity.schemas import (
    CompanyRegisterRequest,
    LoginRequest,
    TokenResponse,
)
from app.core.config import settings


def _generate_company_code(name: str) -> str:
    base = name.upper().replace(" ", "")[:6]
    suffix = uuid.uuid4().hex[:4].upper()
    return f"{base}-{suffix}"


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.company_repo = CompanyRepository(db)
        self.user_repo = UserRepository(db)
        self.token_repo = RefreshTokenRepository(db)

    def register_company(self, data: CompanyRegisterRequest):
        if self.company_repo.get_by_email(data.company_email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A company with this email already exists.",
            )
        if self.user_repo.get_by_email(data.admin_email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )
        company = self.company_repo.create(
            name=data.company_name,
            code=_generate_company_code(data.company_name),
            email=data.company_email,
            phone=data.phone,
            industry=data.industry,
            status=CompanyStatus.active,
        )
        self.user_repo.create(
            company_id=company.id,
            email=data.admin_email,
            hashed_password=hash_password(data.admin_password),
            role=UserRole.hr_admin,
            is_active=True,
        )
        return company

    def login(self, data: LoginRequest) -> TokenResponse:
        user = self.user_repo.get_by_email(data.email)
        if not user or not verify_password(data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is not active.",
            )
        access_token = create_access_token(
            {"sub": str(user.id), "role": user.role.value,
             "company_id": str(user.company_id)}
        )
        raw_refresh = generate_refresh_token()
        self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
        )

    def refresh(self, raw_token: str) -> TokenResponse:
        token_record = self.token_repo.get_by_hash(hash_token(raw_token))
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )
        self.token_repo.revoke(token_record)
        user = self.user_repo.get_by_id(token_record.user_id)
        access_token = create_access_token(
            {"sub": str(user.id), "role": user.role.value,
             "company_id": str(user.company_id)}
        )
        raw_refresh = generate_refresh_token()
        self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
        )