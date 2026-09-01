"""Spec 13.1: `expire_activation_tokens` — scheduled, daily housekeeping."""

import logging

from sqlalchemy import update

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Employee, InvitationStatus
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


@celery_app.task(name="app.workers.tasks.identity.expire_activation_tokens")
def expire_activation_tokens() -> int:
    """13.2 rule 1: takes no arguments, needs none — a genuine cross-tenant
    sweep. 13.2 rule 2: opens its own session and binds the tenant context —
    here as platform admin (no single company_id applies), the same
    narrow, explicit RLS bypass AuthService.preview_activation already uses
    for a pre-auth, cross-tenant `employees` read. 13.2 rule 3: idempotent —
    the WHERE clause only ever matches rows not already marked `expired`.
    """
    db = SessionLocal()
    try:
        bind_tenant_to_session(db, company_id=None, is_platform_admin=True)
        stmt = (
            update(Employee)
            .where(
                Employee.invitation_status == InvitationStatus.sent,
                Employee.activation_expires_at.is_not(None),
                Employee.activation_expires_at < utcnow(),
            )
            .values(invitation_status=InvitationStatus.expired)
        )
        result = db.execute(stmt)
        db.commit()
        # CursorResult at runtime for an UPDATE; Result[Any]'s static type omits rowcount.
        count = result.rowcount  # type: ignore[attr-defined]
        logger.info("activation_tokens_expired", extra={"count": count})
        return count
    finally:
        db.close()
