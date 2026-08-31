import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.identity.models import CompanyStatus, UserRole
from app.modules.identity.repository import (
    CompanyRepository,
    RefreshTokenRepository,
    UserRepository,
)
from app.modules.identity.schemas import (
    CompanyRegisterRequest,
    LoginRequest,
    TokenResponse,
)

# Spec 9.4 defaults. Not yet in app/core/config.py (that buildout is WP-02) — move
# these to settings.MAX_LOGIN_ATTEMPTS / settings.LOCKOUT_MINUTES when it lands.
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


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
            # TODO(WP-02): AppError (ConflictError)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A company with this email already exists.",
            )
        # NOTE(WP-05): this whole registration flow — creating an active
        # hr_admin user directly at registration, and checking admin_email for
        # a duplicate before any company exists to scope it to — is carried
        # forward as-is per the fix plan for this pass (out of scope here) and
        # tracked in docs/RECONCILIATION.md. find_by_email is cross-company by
        # design (7.2); a nonempty result here does not necessarily mean a real
        # conflict once WP-05 builds the real pending -> approved workflow.
        if self.user_repo.find_by_email(data.admin_email):
            # TODO(WP-02): AppError (ConflictError)
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
        self.db.commit()
        return company

    def login(self, payload: LoginRequest, device_info: str | None = None) -> tuple[TokenResponse, str]:
        """Spec 5.3's worked example, in full: cross-company lookup, constant-time
        failure on no match, generic message on wrong password, 409 disambiguation
        on more than one match, lockout and active checks only after a proven
        password (9.3, 9.4).
        """
        # May return more than one row: the same email can exist at two companies
        # (7.2). Includes inactive users, so we can tell "wrong password" from
        # "not activated".
        candidates = self.user_repo.find_by_email(payload.email, payload.company_code)

        matched = [u for u in candidates if verify_password(payload.password, u.hashed_password)]
        if not candidates:
            # Verify against a fixed hash anyway, so response time does not reveal
            # whether the email exists (9.3).
            verify_password(payload.password, DUMMY_HASH)

        if not matched:
            for u in candidates:
                self.user_repo.increment_failed_attempts(u)
                if u.failed_attempts >= MAX_LOGIN_ATTEMPTS:
                    self.user_repo.lock(
                        u, datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
                    )
            self.db.commit()
            # TODO(WP-02): AppError (UnauthorizedError) — deliberately generic (9.3)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if len(matched) > 1:
            # Same email AND same password at two companies. Only someone who
            # already proved the password reaches this branch, so the company
            # names leak nothing.
            # TODO(WP-02): AppError (ConflictError with code="company_required")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "company_required",
                    "message": "This email is registered at more than one company.",
                    "companies": [u.company.name for u in matched],
                },
            )

        user = matched[0]

        # Both checks come after a proven password, for the same reason (9.3).
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            # TODO(WP-02): AppError (AccountLockedError) — 423, not 401 (9.4)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account is locked until {user.locked_until.isoformat()}.",
            )
        if not user.is_active:
            # TODO(WP-02): AppError (AccountInactiveError)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is not active.",
            )

        self.user_repo.reset_failed_attempts(user)
        access_token = create_access_token(
            sub=str(user.id), company_id=str(user.company_id), role=user.role.value
        )
        raw_refresh = generate_refresh_token()
        self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            device_info=device_info,
        )
        self.db.commit()
        return TokenResponse(access_token=access_token), raw_refresh

    def refresh(self, raw_token: str) -> tuple[TokenResponse, str]:
        """Spec 9.2's rotation, in full: not-found, reuse (family revocation),
        and expiry all reject with the same generic 401 before a new pair is ever
        issued.
        """
        token_record = self.token_repo.get_by_hash(hash_token(raw_token))
        if not token_record:
            # TODO(WP-02): AppError (UnauthorizedError)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )

        if token_record.is_revoked:
            # Reuse of an already-rotated token means the token was stolen (9.2
            # step 4) — revoke every refresh token for this user, not just this one.
            for active in self.token_repo.get_active_by_user(token_record.user_id):
                self.token_repo.revoke(active)
            self.db.commit()
            # TODO(WP-11): write an audit_logs entry once the table exists.
            # TODO(WP-02): AppError (UnauthorizedError)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )

        if token_record.expires_at <= datetime.now(timezone.utc):
            # TODO(WP-02): AppError (UnauthorizedError)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )

        user = self.user_repo.get_by_id_for_token_refresh(token_record.user_id)
        if user is None or not user.is_active:
            # TODO(WP-02): AppError (UnauthorizedError)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token.",
            )

        access_token = create_access_token(
            sub=str(user.id), company_id=str(user.company_id), role=user.role.value
        )
        raw_refresh = generate_refresh_token()
        new_token = self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            device_info=token_record.device_info,
        )
        self.token_repo.revoke(token_record, replaced_by=new_token)
        self.db.commit()
        return TokenResponse(access_token=access_token), raw_refresh
