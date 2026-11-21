import uuid
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.core.token_denylist import is_access_token_revoked
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)

INVALID_TOKEN_MESSAGE = "Invalid or expired token."


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: Session = Depends(get_db),
) -> User:
    """Verifies the access token, binds the tenant context from its claims
    BEFORE loading anything, then loads the user (Spec 8.4) — so even this
    lookup, and every query downstream on this session, runs under the
    correct RLS context from the start.
    """
    if credentials is None:
        raise UnauthorizedError("Not authenticated.")

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
        company_id = uuid.UUID(payload["company_id"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE) from exc

    # A token the user logged out with stays dead until it expires.
    if is_access_token_revoked(payload.get("jti")):
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE)

    is_platform_admin = payload.get("role") == UserRole.super_admin.value
    # company_id comes from the verified JWT claim only — never a body,
    # path, query, or header (8.4).
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=is_platform_admin)

    user = UserRepository(db).get_by_id(user_id, company_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE)
    if user.company is None or not user.company.is_active:
        raise UnauthorizedError(INVALID_TOKEN_MESSAGE)

    # F5: Invalidate tokens issued before password_changed_at.
    # Note on the 1-second window: JWT "iat" is serialized in integer seconds.
    # If password_changed_at is recorded within the same sub-second window as token issuance,
    # integer comparison `int(iat) < int(password_changed_at.timestamp())` guarantees that any
    # token issued strictly before the second in which the password changed is immediately rejected.
    # If password_changed_at is NULL, no check is performed.
    if user.password_changed_at is not None:
        token_iat = payload.get("iat")
        if token_iat is not None:
            # iat can be a datetime (if decoded by PyJWT with options) or an int timestamp
            iat_seconds = (
                int(token_iat.timestamp()) if hasattr(token_iat, "timestamp") else int(token_iat)
            )
            pw_changed_seconds = int(user.password_changed_at.timestamp())
            if iat_seconds < pw_changed_seconds:
                raise UnauthorizedError(INVALID_TOKEN_MESSAGE)

    return user


def get_tenant_db(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Session:
    """Every tenant-scoped route depends on this, not get_db. Public routes
    (login, register, activate) use get_db directly (8.4).
    """
    bind_tenant_to_session(
        db,
        company_id=user.company_id,
        is_platform_admin=(user.role == UserRole.super_admin),
    )
    return db


COMPANY_FORBIDDEN_MESSAGE = "You do not have permission to perform this action."
PLATFORM_FORBIDDEN_MESSAGE = "You do not have permission to perform this action."


def require_company_role(*roles: UserRole):
    """Like `require_role` for a company's own data: the listed roles (owner is added where
    hr_admin is allowed) and never super_admin. If no roles are specified, any company user
    is allowed."""

    def _require_company_role(user: User = Depends(get_current_user)) -> User:
        if user.role == UserRole.super_admin:
            raise ForbiddenError(COMPANY_FORBIDDEN_MESSAGE)
        if roles:
            allowed_roles = list(roles)
            if UserRole.hr_admin in roles and UserRole.owner not in allowed_roles:
                allowed_roles.append(UserRole.owner)

            if user.role not in allowed_roles:
                raise ForbiddenError(COMPANY_FORBIDDEN_MESSAGE)
        return user

    setattr(_require_company_role, "_guard", "require_company_role")  # noqa: B010
    setattr(_require_company_role, "_allowed_roles", roles)  # noqa: B010
    return _require_company_role


def require_platform_role():
    """Admits ONLY super_admin and refuses every other role."""
    allowed_roles: tuple[UserRole, ...] = (UserRole.super_admin,)

    def _require_platform_role(user: User = Depends(get_current_user)) -> User:
        if user.role != UserRole.super_admin:
            raise ForbiddenError(PLATFORM_FORBIDDEN_MESSAGE)
        _ = allowed_roles
        return user

    setattr(_require_platform_role, "_guard", "require_platform_role")  # noqa: B010
    setattr(_require_platform_role, "_allowed_roles", allowed_roles)  # noqa: B010
    return _require_platform_role


def get_company_user(user: User = Depends(require_company_role())) -> User:
    """Any logged-in user of a company, except a platform account: company payroll data
    (salaries, runs, payslips, claims, bank details) is never opened to a super admin (5.8)."""
    return user


def require_role(*roles: UserRole):
    """`Depends(require_role(UserRole.hr_admin))` — is this role allowed
    here? (5.1). Composes get_current_user rather than duplicating the
    token/tenant-binding logic.
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        allowed_roles = list(roles)
        if UserRole.hr_admin in roles and UserRole.owner not in allowed_roles:
            allowed_roles.append(UserRole.owner)

        if user.role != UserRole.super_admin and user.role not in allowed_roles:
            raise ForbiddenError("You do not have permission to perform this action.")
        return user

    return _check
