"""Spec 13.1: `expire_activation_tokens` — scheduled, daily housekeeping."""

import logging

from sqlalchemy import update

from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Employee, InvitationStatus
from app.workers.celery_app import celery_app
from app.workers.tasks.email import send_email_task

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


@celery_app.task(name="app.workers.tasks.identity.process_password_reset_request")
def process_password_reset_request(email: str, company_code: str | None = None) -> None:
    """F2: Process password reset request asynchronously in Celery task.
    All lookup, code generation, audit and email work run in this task with its own DB session
    (same pre-auth cross-company lookup pattern as today).
    """
    from app.core.config import settings
    from app.core.email_templates import multi_company_guidance_email, password_reset_otp_email
    from app.core.otp import generate_and_store_otp
    from app.db.session import get_db
    from app.main import app as fastapi_app
    from app.modules.identity.repository import UserRepository
    from app.modules.platform.service import AuditService

    if get_db in fastapi_app.dependency_overrides:
        # Running under test with savepoint isolation (Spec 15.2)
        db_gen = fastapi_app.dependency_overrides[get_db]()
        db = next(db_gen)
        is_override = True
    else:
        db = SessionLocal()
        is_override = False

    try:
        bind_tenant_to_session(db, company_id=None, is_platform_admin=True)
        user_repo = UserRepository(db)
        candidates = user_repo.find_by_email(email, company_code)

        # Filter to active accounts only (J07: unactivated invites & deactivated users get no email)
        active_candidates = [u for u in candidates if u.is_active]

        # Multi-company disambiguation (F4):
        # If email matches more than one company and no code is given:
        # guidance email is sent ("this email is used in more than one workspace..."),
        # no code generated.
        if len(active_candidates) > 1 and not company_code:
            subject, text_body, html_body = multi_company_guidance_email()
            send_email_task.delay(
                to=email, subject=subject, text_body=text_body, html_body=html_body
            )
            return

        if len(active_candidates) == 1:
            user = active_candidates[0]
            otp = generate_and_store_otp(email, company_id=user.company_id)

            # Audit row PASSWORD_RESET_REQUESTED (real accounts only, inside the task)
            AuditService(db).record(
                company_id=user.company_id,
                actor=user,
                action="PASSWORD_RESET_REQUESTED",
                entity_type="user",
                entity_id=user.id,
                details={"email": email},
            )
            db.commit()

            subject, text_body, html_body = password_reset_otp_email(
                otp=otp, expires_minutes=settings.OTP_TTL_MINUTES
            )
            send_email_task.delay(
                to=email, subject=subject, text_body=text_body, html_body=html_body
            )
    finally:
        if not is_override:
            db.close()
