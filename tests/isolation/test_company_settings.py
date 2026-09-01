"""company_settings is the first RLS-protected table (Spec 7.2, 8.3). It has
no HTTP routes of its own yet (those arrive with a later work package), so
these tests exercise the RLS mechanism directly through the session layer —
the same bind_tenant_to_session/get_tenant_db path a future route will use.
"""

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text

from app.core.dependencies import get_current_user
from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import CompanySettings, UserRole


def test_unset_tenant_context_returns_zero_rows_not_all_rows(db, company_a, company_b):
    """The safe failure mode (8.3): company_id = NULL is never true, so an
    unset context returns nothing — never every tenant's rows."""
    db.execute(text("RESET app.current_company_id"))
    db.execute(text("RESET app.is_platform_admin"))

    rows = db.query(CompanySettings).all()

    assert rows == []


def test_company_settings_is_tenant_isolated(db, company_a, company_b):
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)
    rows_as_a = db.query(CompanySettings).all()
    assert [r.company_id for r in rows_as_a] == [company_a.company_id]

    bind_tenant_to_session(db, company_id=company_b.company_id, is_platform_admin=False)
    rows_as_b = db.query(CompanySettings).all()
    assert [r.company_id for r in rows_as_b] == [company_b.company_id]

    # Different rows, not the same set seen twice.
    assert rows_as_a[0].id != rows_as_b[0].id


def test_write_commit_and_read_back_within_one_request_proves_after_begin_listener(db, company_a):
    """Without the after_begin listener, is_local=true clears the tenant
    context on commit, and a service that commits mid-request (6.7) would
    find it gone on the very next query — the cheapest way to catch that
    whole class of bug (8.4).
    """
    bind_tenant_to_session(db, company_id=company_a.company_id, is_platform_admin=False)

    row = db.query(CompanySettings).filter_by(company_id=company_a.company_id).one()
    row.full_day_hours = 9
    db.commit()  # a mid-request commit, exactly like a service (6.7)

    # No explicit re-bind here — if after_begin didn't reapply the context,
    # this next query would run under an unset context and see zero rows.
    refetched = db.query(CompanySettings).filter_by(company_id=company_a.company_id).one()
    assert refetched.full_day_hours == 9


def test_hr_admin_jwt_can_never_set_is_platform_admin(db, company_a):
    """8.5: the cross-tenant isolation suite must assert that a hr_admin
    token can never cause app.is_platform_admin to be set. Exercises the
    real get_current_user dependency with a genuine hr_admin access token,
    not a hand-picked boolean.
    """
    raw_token = company_a.hr_headers["Authorization"].removeprefix("Bearer ")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw_token)

    user = get_current_user(credentials=credentials, db=db)

    assert user.role == UserRole.hr_admin
    flag = db.execute(text("SELECT current_setting('app.is_platform_admin', true)")).scalar()
    assert flag != "on"
