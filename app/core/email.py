"""A minimal stand-in for the real email backend (Spec 13, WP-26 delivers
Celery + SendGrid). `EMAIL_BACKEND=console` — the default, and the only one
exercised in dev/tests — deliberately does NOT route through
app.core.logging's structured JSON pipeline: that pipeline is meant to
reach real log aggregators, and an email body here can carry a
password-reset OTP or an activation link, both secrets Section 6.8 forbids
logging. Printing straight to stdout is the same pattern Django's own
console email backend uses for local development; it is never meant to run
this way in production, where EMAIL_BACKEND=sendgrid replaces it entirely.
"""

from app.core.config import settings


def send_email(*, to: str, subject: str, body: str) -> None:
    if settings.EMAIL_BACKEND == "console":
        print(  # noqa: T201 — the deliberate dev-only "backend", not app logging
            f"----- console email -----\nTo: {to}\nSubject: {subject}\n\n{body}\n"
            "--------------------------"
        )
        return
    raise NotImplementedError("The sendgrid EMAIL_BACKEND is not wired up yet (WP-26).")
