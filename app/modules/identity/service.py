import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, UnauthorizedError
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.time import utcnow
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

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
INVALID_REFRESH_TOKEN_MESSAGE = "Invalid or expired refresh token."


class InvalidCredentialsError(UnauthorizedError):
    """Deliberately generic — wrong email and wrong password look identical
    to the caller (9.3)."""

    def __init__(self) -> None:
        super().__init__(INVALID_CREDENTIALS_MESSAGE)


class CompanyRequiredError(ConflictError):
    """The email matched more than one company; the client must resubmit
    with `company_code` (7.2's design note, 9.2 route 1)."""

    code = "company_required"

    def __init__(self, companies: list[str]) -> None:
        super().__init__(
            "This email is registered at more than one company.",
            details={"companies": companies},
        )


class AccountLockedError(AppError):
    status_code = 423
    code = "account_locked"

    def __init__(self, until: datetime) -> None:
        super().__init__(
            f"Account is locked until {until.isoformat()}.",
            details={"locked_until": until.isoformat()},
        )


class AccountInactiveError(AppError):
    status_code = 403
    code = "account_inactive"

    def __init__(self) -> None:
        super().__init__("Account is not active.")


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
            raise ConflictError("A company with this email already exists.")
        # NOTE(WP-05): this whole registration flow — creating an active
        # hr_admin user directly at registration, and checking admin_email for
        # a duplicate before any company exists to scope it to — is carried
        # forward as-is per the fix plan for this pass (out of scope here) and
        # tracked in docs/RECONCILIATION.md. find_by_email is cross-company by
        # design (7.2); a nonempty result here does not necessarily mean a real
        # conflict once WP-05 builds the real pending -> approved workflow.
        if self.user_repo.find_by_email(data.admin_email):
            raise ConflictError("A user with this email already exists.")
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

    def login(
        self, payload: LoginRequest, device_info: str | None = None
    ) -> tuple[TokenResponse, str]:
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
                if u.failed_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                    self.user_repo.lock(u, utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES))
            self.db.commit()
            raise InvalidCredentialsError()

        if len(matched) > 1:
            # Same email AND same password at two companies. Only someone who
            # already proved the password reaches this branch, so the company
            # names leak nothing.
            raise CompanyRequiredError(companies=[u.company.name for u in matched])

        user = matched[0]

        # Both checks come after a proven password, for the same reason (9.3).
        if user.locked_until and user.locked_until > utcnow():
            raise AccountLockedError(until=user.locked_until)
        if not user.is_active:
            raise AccountInactiveError()

        self.user_repo.reset_failed_attempts(user)
        access_token = create_access_token(
            sub=str(user.id), company_id=str(user.company_id), role=user.role.value
        )
        raw_refresh = generate_refresh_token()
        self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
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
            raise UnauthorizedError(INVALID_REFRESH_TOKEN_MESSAGE)

        if token_record.is_revoked:
            # Reuse of an already-rotated token means the token was stolen (9.2
            # step 4) — revoke every refresh token for this user, not just this one.
            for active in self.token_repo.get_active_by_user(token_record.user_id):
                self.token_repo.revoke(active)
            self.db.commit()
            # TODO(WP-11): write an audit_logs entry once the table exists.
            raise UnauthorizedError(INVALID_REFRESH_TOKEN_MESSAGE)

        if token_record.expires_at <= utcnow():
            raise UnauthorizedError(INVALID_REFRESH_TOKEN_MESSAGE)

        user = self.user_repo.get_by_id_for_token_refresh(token_record.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError(INVALID_REFRESH_TOKEN_MESSAGE)

        access_token = create_access_token(
            sub=str(user.id), company_id=str(user.company_id), role=user.role.value
        )
        raw_refresh = generate_refresh_token()
        new_token = self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            device_info=token_record.device_info,
        )
        self.token_repo.revoke(token_record, replaced_by=new_token)
        self.db.commit()
        return TokenResponse(access_token=access_token), raw_refresh
