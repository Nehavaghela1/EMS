import logging
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email import send_email
from app.core.exceptions import AppError, ConflictError, NotFoundError, UnauthorizedError
from app.core.otp import generate_and_store_otp, verify_otp
from app.core.pagination import PageParams
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, InvitationStatus
from app.modules.hr.repository import DepartmentRepository, EmployeeRepository
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole
from app.modules.identity.repository import (
    CompanyRepository,
    RefreshTokenRepository,
    UserRepository,
)
from app.modules.identity.schemas import (
    ActivateAccountRequest,
    ChangePasswordRequest,
    CompanyProfileUpdateRequest,
    CompanyRegisterRequest,
    EmployeeSummary,
    LoginRequest,
    MeResponse,
    ResetPasswordRequest,
    TokenResponse,
)
from app.modules.platform.repository import IndustryPresetRepository
from app.modules.time_leave.repository import LeaveTypeRepository

logger = logging.getLogger("app")

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
INVALID_REFRESH_TOKEN_MESSAGE = "Invalid or expired refresh token."

# Route 5's "permissions" — a small, deterministic, role-derived capability
# list. The spec defines no dedicated permissions table or schema (Section 7
# has none), so this is a documented judgment call, not a full RBAC engine —
# see RECONCILIATION spec gaps.
_ROLE_PERMISSIONS: dict[UserRole, list[str]] = {
    UserRole.employee: ["view_own_profile", "apply_leave", "mark_attendance"],
    UserRole.manager: [
        "view_own_profile",
        "apply_leave",
        "mark_attendance",
        "view_team",
        "approve_team_leave",
    ],
    UserRole.hr_admin: [
        "view_own_profile",
        "manage_employees",
        "manage_departments",
        "manage_company",
        "approve_leave",
    ],
    UserRole.super_admin: ["manage_platform", "approve_companies"],
}


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


class InvalidCurrentPasswordError(UnauthorizedError):
    """Route 6 — deliberately a distinct message from login's generic one:
    the caller is already authenticated as themselves here, so there is no
    enumeration risk in saying exactly what was wrong (9.3 protects an
    anonymous caller guessing at someone else's credentials, not this)."""

    def __init__(self) -> None:
        super().__init__("Current password is incorrect.")


class InvalidOtpError(AppError):
    """Routes 7-8 — one generic message for "no such OTP", "wrong code",
    "expired", and "attempts exhausted" alike, the same enumeration-safety
    principle 9.3 applies to login."""

    status_code = 400
    code = "invalid_otp"

    def __init__(self) -> None:
        super().__init__("Invalid or expired code.")


class InvalidActivationTokenError(NotFoundError):
    """Routes 10-11 — one message whether the token is malformed, unknown,
    expired, or already redeemed."""

    def __init__(self) -> None:
        super().__init__("Invitation not found or has expired.")


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
        self.employee_repo = EmployeeRepository(db)

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
        # Transparent rehash-on-login (9.1): a stored hash that predates a
        # parameter increase is upgraded the moment we have the plaintext
        # to do it with — this is the only place that plaintext ever exists.
        if needs_rehash(user.hashed_password):
            self.user_repo.update(
                user, user.company_id, hashed_password=hash_password(payload.password)
            )
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

    def logout(self, raw_token: str) -> None:
        """Route 3: revoke just the presented refresh token. Idempotent —
        an absent, already-revoked, or unrecognized cookie is a silent
        no-op, never an error (the caller is logging out either way)."""
        if not raw_token:
            return
        token_record = self.token_repo.get_by_hash(hash_token(raw_token))
        if token_record and not token_record.is_revoked:
            self.token_repo.revoke(token_record)
            self.db.commit()

    def logout_all(self, user_id: uuid.UUID) -> None:
        """Route 4: revoke every active refresh token for this user, across
        every device."""
        for token in self.token_repo.get_active_by_user(user_id):
            self.token_repo.revoke(token)
        self.db.commit()

    def get_me(self, user: User) -> MeResponse:
        """Route 5: current user, linked employee summary (None if the
        caller has no Employee row — e.g. an HR admin created directly at
        company approval, WP-05), and role-derived permissions."""
        employee = self.employee_repo.get_by_user_id(user.company_id, user.id)
        return MeResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            company_id=user.company_id,
            is_active=user.is_active,
            must_change_password=user.must_change_password,
            employee=EmployeeSummary.model_validate(employee) if employee else None,
            permissions=_ROLE_PERMISSIONS.get(user.role, []),
        )

    def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        """Route 6: current + new password; revokes every other session —
        a changed password should not leave old sessions valid."""
        if not verify_password(data.current_password, user.hashed_password):
            raise InvalidCurrentPasswordError()
        self.user_repo.update(
            user, user.company_id, hashed_password=hash_password(data.new_password)
        )
        for token in self.token_repo.get_active_by_user(user.id):
            self.token_repo.revoke(token)
        self.db.commit()

    def forgot_password(self, email: str) -> None:
        """Route 7. The router always returns the same 200 regardless of
        what happens in here (9.3) — this method's return value is never
        branched on by the caller. Only sends when exactly one active
        account matches: zero matches and more-than-one matches (ambiguous
        — which account?) are both silent no-ops, indistinguishable to the
        caller from the real case either way.
        """
        users = self.user_repo.find_by_email(email)
        if len(users) == 1 and users[0].is_active:
            otp = generate_and_store_otp(email)
            send_email(
                to=email,
                subject="Your EMS Pro password reset code",
                body=(
                    f"Your password reset code is {otp}. "
                    f"It expires in {settings.OTP_TTL_MINUTES} minutes."
                ),
            )

    def reset_password(self, data: ResetPasswordRequest) -> None:
        """Route 8: OTP + new password. Also revokes every existing
        session, same reasoning as change-password."""
        if not verify_otp(data.email, data.otp):
            raise InvalidOtpError()
        users = self.user_repo.find_by_email(data.email)
        if len(users) != 1:
            # Unreachable in practice — forgot_password only ever issues an
            # OTP for exactly one match — but never silently succeed on an
            # unexpected shape.
            raise InvalidOtpError()
        user = users[0]
        self.user_repo.update(
            user, user.company_id, hashed_password=hash_password(data.new_password)
        )
        for token in self.token_repo.get_active_by_user(user.id):
            self.token_repo.revoke(token)
        self.db.commit()

    def check_username_available(self, username: str) -> bool:
        """Route 9 — see UserRepository.username_taken_anywhere's docstring
        for why this is platform-wide rather than per-company."""
        return not self.user_repo.username_taken_anywhere(username)

    def preview_activation(self, raw_token: str) -> tuple[Employee, Company]:
        """Route 10, and the first half of route 11. `employees` IS RLS-
        protected (unlike users/refresh_tokens), so this explicitly binds
        platform-admin context to run a lookup that has no tenant yet —
        the same reasoning CompanyService.approve_company already uses to
        act across a tenant boundary (8.5), narrowed here to a single,
        secret-gated read.
        """
        bind_tenant_to_session(self.db, company_id=None, is_platform_admin=True)
        employee = self.employee_repo.get_by_activation_token_hash(hash_token(raw_token))
        if (
            employee is None
            or employee.invitation_status == InvitationStatus.activated
            or employee.activation_expires_at is None
            or employee.activation_expires_at <= utcnow()
        ):
            raise InvalidActivationTokenError()
        company = self.company_repo.get_by_id(employee.company_id)
        assert company is not None  # FK guarantees this
        return employee, company

    def activate_employee(self, data: ActivateAccountRequest) -> tuple[TokenResponse, str]:
        """Route 11: token + username + password activates the employee's
        user account and logs them straight in — the same token pair shape
        login() issues, so the frontend needs no separate login step right
        after activating."""
        employee, _company = self.preview_activation(data.token)

        if self.user_repo.get_by_username(employee.company_id, data.username):
            raise ConflictError("Username is already taken.")

        user = self.user_repo.create(
            company_id=employee.company_id,
            email=employee.email,
            username=data.username,
            hashed_password=hash_password(data.password),
            role=UserRole.employee,
            is_active=True,
        )
        self.employee_repo.activate(employee, user_id=user.id)

        access_token = create_access_token(
            sub=str(user.id), company_id=str(user.company_id), role=user.role.value
        )
        raw_refresh = generate_refresh_token()
        self.token_repo.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self.db.commit()
        return TokenResponse(access_token=access_token), raw_refresh


class CompanyService:
    """Routes 12-18 (10.2): public registration, super-admin list/approve/
    reject, and self-service company profile.
    """

    def __init__(self, db: Session):
        self.db = db
        self.company_repo = CompanyRepository(db)
        self.user_repo = UserRepository(db)
        self.department_repo = DepartmentRepository(db)
        self.leave_type_repo = LeaveTypeRepository(db)
        self.industry_preset_repo = IndustryPresetRepository(db)

    def register_company(self, data: CompanyRegisterRequest) -> Company:
        """Route 12: company self-registration only, status = pending. No
        user is created here — the HR admin is created at approval (route
        15), in one transaction with the rest of onboarding.
        """
        if self.company_repo.get_by_email(data.company_email):
            raise ConflictError("A company with this email already exists.")
        company = self.company_repo.create(
            name=data.company_name,
            code=_generate_company_code(data.company_name),
            email=data.company_email,
            phone=data.phone,
            industry=data.industry,
            country=data.country,
            status=CompanyStatus.pending,
        )
        self.db.commit()
        return company

    def list_companies(
        self,
        *,
        status: CompanyStatus | None,
        q: str | None,
        country: str | None,
        sort: str | None,
        page_params: PageParams,
    ) -> tuple[list[Company], int, int]:
        """Route 13, SA only."""
        return self.company_repo.list_companies(
            status=status, q=q, country=country, sort=sort, page_params=page_params
        )

    def get_company_detail(self, company_id: uuid.UUID) -> tuple[Company, dict[str, int]]:
        """Route 14, SA only. Counts currently cover what exists: users and
        departments. Employees join once WP-07 lands.
        """
        company = self.company_repo.get_by_id(company_id)
        if company is None:
            raise NotFoundError("Company not found.")
        counts = {
            "users": self.user_repo.count_by_company(company_id),
            "departments": self.department_repo.count_by_company(company_id),
        }
        return company, counts

    def approve_company(
        self, company_id: uuid.UUID, admin_id: uuid.UUID
    ) -> tuple[Company, str, str]:
        """Route 15, SA only. Seeds the company's company_settings row,
        default departments and leave types from its industry preset (when
        it has a recognized industry), and creates the HR admin — one
        transaction (6.7): if any step fails, the company is left exactly
        as it was, still pending.
        """
        company = self.company_repo.get_by_id(company_id)
        if company is None:
            raise NotFoundError("Company not found.")
        if company.status != CompanyStatus.pending:
            raise ConflictError(
                f"Company is not pending approval (current status: {company.status.value})."
            )

        # Acting on another tenant's data as the platform admin (8.5) — bind
        # to the target company explicitly, for clarity and auditability,
        # even though is_platform_admin=True already bypasses the check.
        bind_tenant_to_session(self.db, company_id=company.id, is_platform_admin=True)

        self.company_repo.update(
            company, status=CompanyStatus.active, approved_at=utcnow(), approved_by=admin_id
        )

        self.db.add(CompanySettings(company_id=company.id))

        if company.industry:
            preset = self.industry_preset_repo.get_by_name(company.industry)
            if preset:
                for dept in preset.departments_json:
                    self.department_repo.create(company_id=company.id, name=dept["name"])
                for leave_type in preset.leave_types_json:
                    self.leave_type_repo.create(
                        company_id=company.id,
                        name=leave_type["name"],
                        code=leave_type["code"],
                        annual_allowance=Decimal(str(leave_type["annual_allowance"])),
                        carry_forward_limit=Decimal(str(leave_type["carry_forward_limit"])),
                        max_consecutive_days=leave_type["max_consecutive_days"],
                        is_paid=leave_type["is_paid"],
                        is_encashable=leave_type["is_encashable"],
                    )

        raw_password = secrets.token_urlsafe(12)
        hr_admin = self.user_repo.create(
            company_id=company.id,
            email=company.email,
            hashed_password=hash_password(raw_password),
            role=UserRole.hr_admin,
            is_active=True,
            must_change_password=True,
        )
        # No email backend is wired up yet (WP-26 replaces this). Never log
        # the password (6.8, rule 10) — it leaves this function exactly once,
        # in the return value, for the router to hand back to the SA caller.
        logger.info(
            "hr_admin_created_at_approval",
            extra={"company_id": str(company.id), "hr_admin_email": hr_admin.email},
        )

        self.db.commit()
        return company, hr_admin.email, raw_password

    def reject_company(self, company_id: uuid.UUID, reason: str) -> Company:
        """Route 16, SA only."""
        company = self.company_repo.get_by_id(company_id)
        if company is None:
            raise NotFoundError("Company not found.")
        if company.status != CompanyStatus.pending:
            raise ConflictError(
                f"Company is not pending approval (current status: {company.status.value})."
            )
        self.company_repo.update(company, status=CompanyStatus.rejected, rejection_reason=reason)
        self.db.commit()
        return company

    def get_my_company(self, company_id: uuid.UUID) -> Company:
        """Route 17. `company_id` is always the caller's own, from the
        verified JWT claim — never a path parameter, so there is no
        cross-tenant surface here to begin with.
        """
        company = self.company_repo.get_by_id(company_id)
        if company is None:
            raise NotFoundError("Company not found.")
        return company

    def update_my_company(
        self, company_id: uuid.UUID, data: CompanyProfileUpdateRequest
    ) -> Company:
        """Route 18, HR only."""
        company = self.company_repo.get_by_id(company_id)
        if company is None:
            raise NotFoundError("Company not found.")
        updates = data.model_dump(exclude_unset=True)
        self.company_repo.update(company, **updates)
        self.db.commit()
        return company
