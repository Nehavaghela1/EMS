"""Part 1: the console backend, asserted directly — recipient, subject,
whether a link/OTP is present — and the smtp/resend backends' request
shape and transient/permanent classification, entirely mocked. No test in
this file (or anywhere else in the suite) ever opens a socket or makes a
network call.
"""

import smtplib
import urllib.error

import pytest

from app.core import email as email_module
from app.core.email import PermanentEmailError, TransientEmailError, send_email
from app.workers.tasks.email import send_email_task


@pytest.fixture(autouse=True)
def _clear_outbox():
    email_module.console_outbox.clear()
    yield
    email_module.console_outbox.clear()


def test_console_backend_records_recipient_subject_and_body(monkeypatch):
    monkeypatch.setattr(email_module.settings, "EMAIL_BACKEND", "console")
    send_email(
        to="jane@example.com",
        subject="You're invited to join Acme on EMS",
        text_body="Activate your account: http://localhost:5173/activate/abc123",
        html_body="<p>Activate your account: <a href='...'>here</a></p>",
    )
    assert len(email_module.console_outbox) == 1
    sent = email_module.console_outbox[0]
    assert sent["to"] == "jane@example.com"
    assert "invited" in sent["subject"]
    assert "/activate/abc123" in sent["text_body"]


def test_console_backend_never_touches_smtp_or_urllib(monkeypatch):
    """The whole point of console being the test default: no socket, ever."""
    monkeypatch.setattr(email_module.settings, "EMAIL_BACKEND", "console")

    def _fail(*args, **kwargs):
        raise AssertionError("console backend must never open a socket")

    monkeypatch.setattr(smtplib, "SMTP", _fail)
    monkeypatch.setattr("urllib.request.urlopen", _fail)
    send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


# --- smtp backend: mocked, no real connection ever made --------------------


class _FakeSMTP:
    """Records what would have happened, raises what a test asks it to."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.starttls_called = False
        self.login_args: tuple | None = None
        self.sent_message = None
        self.raise_on: Exception | None = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        if self.raise_on:
            raise self.raise_on
        self.sent_message = message


def _configure_smtp(monkeypatch, *, raise_on: Exception | None = None):
    _FakeSMTP.instances.clear()

    def _factory(host, port, timeout=None):
        instance = _FakeSMTP(host, port, timeout)
        instance.raise_on = raise_on
        return instance

    monkeypatch.setattr(smtplib, "SMTP", _factory)
    monkeypatch.setattr(email_module.settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(email_module.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_module.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(email_module.settings, "SMTP_USERNAME", "bot@example.com")
    monkeypatch.setattr(email_module.settings, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(email_module.settings, "SMTP_USE_TLS", True)


def test_smtp_backend_uses_starttls_and_logs_in(monkeypatch):
    _configure_smtp(monkeypatch)
    send_email(to="a@b.com", subject="Hi", text_body="text", html_body="<p>html</p>")

    instance = _FakeSMTP.instances[0]
    assert instance.host == "smtp.example.com"
    assert instance.starttls_called is True
    assert instance.login_args == ("bot@example.com", "app-password")
    assert instance.sent_message["To"] == "a@b.com"
    assert instance.sent_message["Subject"] == "Hi"
    # Both parts present — plain-text alternative, not HTML-only (Part 1).
    parts = instance.sent_message.get_payload()
    content_types = {p.get_content_type() for p in parts}
    assert content_types == {"text/plain", "text/html"}


def test_smtp_auth_failure_is_permanent(monkeypatch):
    _configure_smtp(monkeypatch, raise_on=smtplib.SMTPAuthenticationError(535, b"bad credentials"))
    with pytest.raises(PermanentEmailError):
        send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


def test_smtp_recipient_refused_is_permanent(monkeypatch):
    _configure_smtp(
        monkeypatch, raise_on=smtplib.SMTPRecipientsRefused({"a@b.com": (550, b"no such user")})
    )
    with pytest.raises(PermanentEmailError):
        send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


def test_smtp_connection_refused_is_transient(monkeypatch):
    _configure_smtp(monkeypatch)
    monkeypatch.setattr(
        smtplib,
        "SMTP",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError("connection refused")),
    )
    with pytest.raises(TransientEmailError):
        send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


# --- resend backend: mocked HTTP, no real request ever made ----------------


class _FakeHTTPResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _configure_resend(monkeypatch):
    monkeypatch.setattr(email_module.settings, "EMAIL_BACKEND", "resend")
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(email_module.settings, "EMAIL_FROM", "noreply@example.com")


def test_resend_backend_sends_the_expected_payload_and_auth_header(monkeypatch):
    _configure_resend(monkeypatch)
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        return _FakeHTTPResponse(200)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    send_email(to="a@b.com", subject="Hi", text_body="text", html_body="<p>html</p>")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test_key"
    assert b'"to": ["a@b.com"]' in captured["body"]


def test_resend_auth_error_is_permanent(monkeypatch):
    _configure_resend(monkeypatch)

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(PermanentEmailError):
        send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


def test_resend_rate_limit_is_transient(monkeypatch):
    _configure_resend(monkeypatch)

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 429, "too many requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(TransientEmailError):
        send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


def test_resend_unreachable_is_transient(monkeypatch):
    _configure_resend(monkeypatch)

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(TransientEmailError):
        send_email(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


# --- the Celery task: permanent failures are logged and dropped -------------


def test_task_swallows_a_permanent_failure_without_raising(monkeypatch):
    monkeypatch.setattr(
        "app.workers.tasks.email.send_email",
        lambda **kwargs: (_ for _ in ()).throw(PermanentEmailError("bad address")),
    )
    # Calling the task directly (not .delay()/.apply()) runs its body once,
    # synchronously, no Celery machinery involved — proves the except
    # PermanentEmailError branch, not Celery's own retry/error handling.
    send_email_task(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


def test_task_does_not_swallow_a_transient_failure(monkeypatch):
    """TransientEmailError must propagate out of the task body — that's
    what autoretry_for=(TransientEmailError,) on the task decorator (Spec
    13.2 rule 6) needs to see in order to retry it."""
    monkeypatch.setattr(
        "app.workers.tasks.email.send_email",
        lambda **kwargs: (_ for _ in ()).throw(TransientEmailError("connection refused")),
    )
    with pytest.raises(TransientEmailError):
        send_email_task(to="a@b.com", subject="s", text_body="t", html_body="<p>t</p>")


def test_task_is_configured_to_retry_only_transient_errors():
    assert send_email_task.autoretry_for == (TransientEmailError,)
    assert send_email_task.retry_backoff is True
    assert send_email_task.max_retries == 3
