"""Every email this project sends, in one place. Plain, readable HTML with
a plain-text alternative — no images, no tracking pixels, no external
assets (Spec 9's own spirit: this is a transactional HRMS email, not a
marketing one). A password, token, or OTP appears only in the message
body, never in a subject line (a subject often survives in notification
previews, push banners, and mail server logs even when the body doesn't).
"""

from datetime import datetime

_STYLE = (
    "font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px;"
    "line-height:1.5;color:#1a1d23;max-width:480px;margin:0 auto;padding:24px"
)
_BUTTON_STYLE = (
    "display:inline-block;background:#2f5bea;color:#ffffff;text-decoration:none;"
    "padding:10px 20px;border-radius:6px;font-weight:600"
)


def _wrap_html(body: str) -> str:
    footer = '<p style="color:#8a90a0;font-size:13px;margin-top:32px">EMS</p>'
    return f'<div style="{_STYLE}">{body}{footer}</div>'


def _fmt(dt: datetime) -> str:
    return dt.strftime("%B %d, %Y at %H:%M UTC")


def employee_invitation_email(
    *, first_name: str, company_name: str, activation_link: str, expires_at: datetime
) -> tuple[str, str, str]:
    """Route 20/26 — sent instead of returning the raw activation token in
    the API response (that was always an MVP stand-in for this)."""
    subject = f"You're invited to join {company_name} on EMS"
    text = (
        f"Hi {first_name},\n\n"
        f"{company_name} has invited you to set up your EMS account.\n\n"
        f"Activate your account: {activation_link}\n\n"
        f"This link expires {_fmt(expires_at)}.\n\n"
        "If you weren't expecting this, you can safely ignore this email."
    )
    html = _wrap_html(
        f"<p>Hi {first_name},</p>"
        f"<p>{company_name} has invited you to set up your EMS account.</p>"
        f'<p><a href="{activation_link}" style="{_BUTTON_STYLE}">Activate your account</a></p>'
        f"<p>This link expires {_fmt(expires_at)}.</p>"
        "<p>If you weren't expecting this, you can safely ignore this email.</p>"
    )
    return subject, text, html


def password_reset_otp_email(*, otp: str, expires_minutes: int) -> tuple[str, str, str]:
    """Route 7 — the Redis-backed OTP (7.9) was already correct; it just had
    nowhere to go."""
    subject = "Your EMS password reset code"
    ignore_line = "If you didn't request this, you can safely ignore this email."
    text = (
        f"Your password reset code is {otp}.\n\n"
        f"It expires in {expires_minutes} minutes.\n\n"
        f"{ignore_line}"
    )
    otp_style = "font-size:28px;font-weight:700;letter-spacing:0.08em"
    html = _wrap_html(
        f'<p>Your password reset code is:</p><p style="{otp_style}">{otp}</p>'
        f"<p>It expires in {expires_minutes} minutes.</p>"
        f"<p>{ignore_line}</p>"
    )
    return subject, text, html


def hr_admin_credentials_email(
    *, company_name: str, email: str, temporary_password: str, login_link: str
) -> tuple[str, str, str]:
    """Route 15 (company approval) — sent instead of returning the raw
    temporary password in the API response."""
    subject = f"Your EMS admin account for {company_name} is ready"
    text = (
        f"{company_name} has been approved on EMS.\n\n"
        f"Sign in at {login_link} with:\n"
        f"  Email: {email}\n"
        f"  Temporary password: {temporary_password}\n\n"
        "You'll be asked to change this password the first time you sign in."
    )
    html = _wrap_html(
        f"<p>{company_name} has been approved on EMS.</p>"
        f'<p>Sign in at <a href="{login_link}">{login_link}</a> with:</p>'
        f"<p>Email: {email}<br>Temporary password: <strong>{temporary_password}</strong></p>"
        "<p>You'll be asked to change this password the first time you sign in.</p>"
    )
    return subject, text, html


def password_changed_email(*, first_name: str) -> tuple[str, str, str]:
    """Route 6 (change-password) and route 8 (reset-password) — both already
    revoke every other session; this confirms it happened."""
    subject = "Your EMS password was changed"
    signed_out_line = (
        "Your EMS password was just changed, and every other signed-in session was signed out."
    )
    warning = "If this wasn't you, contact your HR admin immediately."
    text = f"Hi {first_name},\n\n{signed_out_line}\n\n{warning}"
    html = _wrap_html(f"<p>Hi {first_name},</p><p>{signed_out_line}</p><p>{warning}</p>")
    return subject, text, html


def leave_decision_email(
    *, first_name: str, status: str, start_date: str, end_date: str, rejection_reason: str | None
) -> tuple[str, str, str]:
    """Route 64 — matches the in-app notification WP-11 already emits for
    the same event, now also as email."""
    verb = "approved" if status == "approved" else "rejected"
    subject = f"Your leave request was {verb}"
    reason_line = f" Reason: {rejection_reason}" if rejection_reason else ""
    dates = f"from {start_date} to {end_date}"
    text = f"Hi {first_name},\n\nYour leave request {dates} was {verb}.{reason_line}"
    html = _wrap_html(
        f"<p>Hi {first_name},</p>"
        f"<p>Your leave request {dates} was <strong>{verb}</strong>.{reason_line}</p>"
    )
    return subject, text, html
