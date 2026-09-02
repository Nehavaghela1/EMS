"""Spec 13.1's `send_email` task. Deliberately takes only primitive strings,
never an id to re-fetch from the database: a rendered activation link, OTP,
or temporary password cannot be recovered later (each is stored hashed or
not at all — 9.10, 7.3, 7.9), so the caller renders the template with what
it already has in memory and hands this task only the finished subject/
text/html — the one thing worth moving off the request path is the network
call itself, not the (cheap, in-memory) rendering."""

import logging

from app.core.email import PermanentEmailError, TransientEmailError, send_email
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


@celery_app.task(
    name="app.workers.tasks.email.send_email_task",
    autoretry_for=(TransientEmailError,),
    retry_backoff=True,
    max_retries=3,
)
def send_email_task(*, to: str, subject: str, text_body: str, html_body: str) -> None:
    try:
        send_email(to=to, subject=subject, text_body=text_body, html_body=html_body)
    except PermanentEmailError as exc:
        # Never re-raised: a rejected address or bad auth will fail the
        # same way every retry, so this is logged and dropped (13.2 rule 5)
        # rather than exhausting max_retries on something that can't
        # possibly succeed. The subject is safe to log; the body (which may
        # carry an OTP/token/password) never is (6.8).
        logger.error(
            "email_delivery_failed_permanently",
            extra={"to": to, "subject": subject, "error": str(exc)},
        )
