import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.pagination import PageParams, paginate, resolve_sort
from app.core.time import utcnow
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, RefreshToken, User


class CompanySettingsRepository:
    """`company_settings` is the single authority on the working week,
    half-day threshold and leave-year convention (7.2) — read by both
    WP-09 (attendance) and WP-10 (leave) rather than each re-deriving it."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_company(self, company_id: uuid.UUID) -> CompanySettings | None:
        return self.db.scalar(
            select(CompanySettings).where(CompanySettings.company_id == company_id)
        )


class CompanyRepository:
    SORT_COLUMNS = {
        "name": Company.name,
        "created_at": Company.created_at,
        "status": Company.status,
    }

    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> Company | None:
        return self.db.scalar(select(Company).where(func.lower(Company.email) == email.lower()))

    def get_by_code(self, code: str) -> Company | None:
        return self.db.scalar(select(Company).where(func.lower(Company.code) == code.lower()))

    def get_by_id(self, company_id: uuid.UUID) -> Company | None:
        return self.db.get(Company, company_id)

    def list_companies(
        self,
        *,
        status: CompanyStatus | None,
        q: str | None,
        country: str | None,
        sort: str | None,
        page_params: PageParams,
    ) -> tuple[list[Company], int, int]:
        stmt = select(Company)
        if status is not None:
            stmt = stmt.where(Company.status == status)
        if country is not None:
            stmt = stmt.where(Company.country == country)
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(
                func.lower(Company.name).like(pattern) | func.lower(Company.code).like(pattern)
            )
        order = resolve_sort(sort, self.SORT_COLUMNS, default=Company.created_at.desc())
        stmt = stmt.order_by(order)
        return paginate(self.db, stmt, page_params)

    def create(self, **kwargs) -> Company:
        company = Company(**kwargs)
        self.db.add(company)
        self.db.flush()
        return company

    def update(self, company: Company, **kwargs) -> Company:
        for key, value in kwargs.items():
            setattr(company, key, value)
        self.db.flush()
        return company

    def increment_employee_seq(self, company_id: uuid.UUID) -> tuple[int, str]:
        """Spec 11.2: concurrency-safe employee_code generation. `UPDATE ...
        RETURNING` takes a row lock on the company for the transaction's
        duration, so a concurrent request blocks until this one commits and
        then gets the next number — never `count(*) + 1`, which is a race
        condition the unique constraint would surface as a 500 under load.
        `companies` has no RLS (7.2), so no tenant context is needed here.
        """
        row = self.db.execute(
            text(
                "UPDATE companies SET last_employee_seq = last_employee_seq + 1 "
                "WHERE id = :company_id RETURNING last_employee_seq, code"
            ),
            {"company_id": str(company_id)},
        ).one()
        return row.last_employee_seq, row.code


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

    def get_by_username(self, company_id: uuid.UUID, username: str) -> User | None:
        """Company-scoped, matching `uq_users_company_id_username`'s actual
        uniqueness shape — used by activation (route 11), where the target
        company is already known from the activation token."""
        return self.db.scalar(
            select(User).where(
                User.company_id == company_id, func.lower(User.username) == username.lower()
            )
        )

    def username_taken_anywhere(self, username: str) -> bool:
        """A fifth pre-authentication-shaped, cross-company lookup (7.2
        names four; `get_by_id_for_token_refresh` was the first one added
        beyond those, WP-01/WP-04) — `GET /auth/check-username/{username}`
        (route 9) is public and has no company context to scope by yet, so
        this checks platform-wide as a conservative UX pre-check only. It
        reveals nothing sensitive (a username's existence, not whose), and
        the real, correctly per-company-scoped enforcement is `get_by_username`
        above plus the database's own unique constraint at activation time.
        """
        return (
            self.db.scalar(select(User.id).where(func.lower(User.username) == username.lower()))
            is not None
        )

    def count_by_company(self, company_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count()).select_from(User).where(User.company_id == company_id)
            )
            or 0
        )

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
