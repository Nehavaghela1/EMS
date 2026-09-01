import uuid
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
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

    is_platform_admin = payload.get("role") == UserRole.super_admin.value
    # company_id comes from the verified JWT claim only — never a body,
    # path, query, or header (8.4).
    bind_tenant_to_session(db, company_id=company_id, is_platform_admin=is_platform_admin)

    user = UserRepository(db).get_by_id(user_id, company_id)
    if user is None or not user.is_active:
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


def require_role(*roles: UserRole):
    """`Depends(require_role(UserRole.hr_admin))` — is this role allowed
    here? (5.1). Composes get_current_user rather than duplicating the
    token/tenant-binding logic.
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to perform this action.")
        return user

    return _check
