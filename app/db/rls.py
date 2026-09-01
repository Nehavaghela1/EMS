import uuid

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from alembic import op


def enable_rls(table: str) -> None:
    """Alembic migration helper (Spec 8.3). ENABLE + FORCE row level security,
    plus a `tenant_isolation` policy with both USING and WITH CHECK. One
    function call per tenant table, in the same migration that creates it —
    see the "add a new tenant table" checklist in the spec's Appendix A.

    `table` is always a literal the migration author supplies, never
    end-user input, so the f-string here is the same pattern the spec's own
    example uses — not a bind-parameter injection risk.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
               OR current_setting('app.is_platform_admin', true) = 'on')
        WITH CHECK (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
                    OR current_setting('app.is_platform_admin', true) = 'on');
    """)


def _apply_tenant_settings(
    executable, company_id: uuid.UUID | None, is_platform_admin: bool
) -> None:
    # Works against either a Session or a Core Connection — both share a
    # compatible .execute(text(...), params) signature. The distinction
    # matters below: the after_begin listener MUST use the raw Connection,
    # not the Session (see its docstring).
    executable.execute(
        text("SELECT set_config('app.current_company_id', :cid, true)"),
        {"cid": str(company_id) if company_id else ""},
    )
    executable.execute(
        text("SELECT set_config('app.is_platform_admin', :flag, true)"),
        {"flag": "on" if is_platform_admin else "off"},
    )


def set_tenant_context(db: Session, company_id: uuid.UUID | None, is_platform_admin: bool) -> None:
    """Spec 8.4. `set_config(..., is_local=true)` is the parameterizable
    equivalent of `SET LOCAL` — `SET LOCAL` itself cannot take bind
    parameters, and string-building it would be an injection risk.
    """
    _apply_tenant_settings(db, company_id, is_platform_admin)


def bind_tenant_to_session(
    db: Session, company_id: uuid.UUID | None, is_platform_admin: bool
) -> None:
    """Apply the tenant context now, and again automatically after every
    commit (Spec 8.4).

    `is_local=true` scopes the setting to the current transaction, which is
    exactly what makes it safe with a connection pool — a leaked
    session-level setting would hand the next request the previous tenant's
    context. But it also means the setting is cleared on every commit, and
    services commit mid-request (6.7): calling set_tenant_context() once per
    request is NOT enough. `db.info["tenant"]` records what to re-apply, and
    the `after_begin` listener below does so at the start of every
    transaction on this session, not just the first.
    """
    db.info["tenant"] = (company_id, is_platform_admin)
    set_tenant_context(db, company_id, is_platform_admin)


@event.listens_for(Session, "after_begin")
def _reapply_tenant_context(session, transaction, connection):
    """Fires at the start of every transaction on this session — including
    ones the session opens implicitly, e.g. to refresh an expired attribute
    right after a commit. It must execute against the raw `connection`
    Core object the event hands us, NOT call back into `session.execute()`:
    the session is still mid-provisioning-a-connection at this exact point,
    and re-entering it raises "This session is provisioning a new
    connection; concurrent operations are not permitted." The Core
    connection itself is already usable. Found the hard way in WP-04's own
    isolation tests, where a post-commit attribute access on an expired ORM
    object was enough to trigger it.
    """
    ctx = session.info.get("tenant")
    if ctx is not None:
        _apply_tenant_settings(connection, *ctx)
