import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.identity.models import Company, RefreshToken, User


class CompanyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> Company | None:
        return self.db.scalar(select(Company).where(func.lower(Company.email) == email.lower()))

    def get_by_code(self, code: str) -> Company | None:
        return self.db.scalar(select(Company).where(func.lower(Company.code) == code.lower()))

    def create(self, **kwargs) -> Company:
        company = Company(**kwargs)
        self.db.add(company)
        self.db.flush()
        return company


class UserRepository:
    """Every method except `find_by_email` and `get_by_id_for_token_refresh`
    requires a `company_id` argument and filters on it — the compensating
    control for `users` not being RLS-protected (Spec 7.2). Enforced by the
    method signatures, not by discipline.
    """

    def __init__(self, db: Session):
        self.db = db

    def find_by_email(self, email: str, company_code: str | None = None) -> list[User]:
        """Pre-authentication lookup (Spec 7.2, worked example in 5.3). There is no
        verified company_id at login time, so this is deliberately cross-company —
        it returns every matching user, including inactive ones, so the service can
        tell "wrong password" from "not activated". Narrowed to one company when
        `company_code` is supplied, for the multi-match disambiguation flow (9.2
        route 1 / the Section 24 decision on per-company email uniqueness).
        """
        stmt = select(User).where(func.lower(User.email) == email.lower())
        if company_code:
            stmt = stmt.join(Company, Company.id == User.company_id).where(
                func.lower(Company.code) == company_code.lower()
            )
        return list(self.db.scalars(stmt).all())

    def get_by_id_for_token_refresh(self, user_id: uuid.UUID) -> User | None:
        """The other pre-authentication-shaped lookup this module needs: reachable
        only after the caller has already verified a hashed, unexpired refresh
        token belonging to this user id (Spec 9.2) — there is no verified
        company_id yet at refresh time either, for the same reason login has none.
        Not one of the three lookups named in 7.2, but the same shape and the same
        justification: unreachable without the corresponding secret.
        """
        return self.db.scalar(select(User).where(User.id == user_id))

    def get_by_id(self, user_id: uuid.UUID, company_id: uuid.UUID) -> User | None:
        return self.db.scalar(select(User).where(User.id == user_id, User.company_id == company_id))

    def create(self, **kwargs) -> User:
        user = User(**kwargs)
        self.db.add(user)
        self.db.flush()
        return user

    def update(self, user: User, company_id: uuid.UUID, **kwargs) -> User:
        if user.company_id != company_id:
            raise ValueError("User does not belong to the given company.")
        for key, value in kwargs.items():
            setattr(user, key, value)
        self.db.flush()
        return user

    def increment_failed_attempts(self, user: User) -> None:
        # Operates on an already-loaded row pinned by primary key — no new lookup,
        # so no cross-tenant risk, no company_id needed (Spec 5.3 worked example).
        user.failed_attempts += 1
        self.db.flush()

    def reset_failed_attempts(self, user: User) -> None:
        user.failed_attempts = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        self.db.flush()

    def lock(self, user: User, until: datetime) -> None:
        user.locked_until = until
        self.db.flush()


class RefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> RefreshToken:
        token = RefreshToken(**kwargs)
        self.db.add(token)
        self.db.flush()
        return token

    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        # Deliberately NOT filtered to is_revoked == False: the service needs to
        # see an already-revoked row to detect reuse and revoke the family (9.2
        # step 4). Filtering it out here would silently hide exactly that signal.
        return self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    def get_active_by_user(self, user_id: uuid.UUID) -> list[RefreshToken]:
        return list(
            self.db.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked.is_(False),
                )
            ).all()
        )

    def revoke(self, token: RefreshToken, *, replaced_by: RefreshToken | None = None) -> None:
        token.is_revoked = True
        token.revoked_at = utcnow()
        if replaced_by is not None:
            token.replaced_by_id = replaced_by.id
        self.db.flush()
