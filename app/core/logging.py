import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

# Set by the request-ID middleware (16.2) so every log line inside a request
# carries it automatically, without threading it through every call site.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_STANDARD_LOG_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
}


_REDACT_KEYS = {
    "password",
    "new_password",
    "current_password",
    "otp",
    "token",
    "refresh_token",
    "authorization",
    "cookie",
    "text_body",
    "html_body",
}


def _scrub_value(val: Any) -> Any:
    if isinstance(val, dict):
        scrubbed = {}
        for k, v in val.items():
            if str(k).lower() in _REDACT_KEYS:
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = _scrub_value(v)
        return scrubbed
    if isinstance(val, (list, tuple)):
        return [_scrub_value(v) for v in val]
    return val


class SecretRedactionFilter(logging.Filter):
    """F8: Redact secrets in logs.
    Removes data.args and data.kwargs from celery.app.trace records while keeping
    task name, id, and runtime.
    For all log records, redacts keys: password, new_password, current_password,
    otp, token, refresh_token, authorization, cookie, text_body, html_body.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 1. Celery trace records: remove args/kwargs from data
        if record.name == "celery.app.trace" or hasattr(record, "data"):
            data = getattr(record, "data", None)
            if isinstance(data, dict):
                # Remove args and kwargs from Celery trace data dictionary
                data.pop("args", None)
                data.pop("kwargs", None)
                record.data = _scrub_value(data)

        # 2. Scrub args
        if isinstance(record.args, dict):
            record.args = _scrub_value(record.args)  # type: ignore[assignment]
        elif isinstance(record.args, (list, tuple)):
            record.args = tuple(_scrub_value(a) for a in record.args)

        # 3. Scrub record attributes / extras
        for key, val in list(record.__dict__.items()):
            if key in _STANDARD_LOG_RECORD_FIELDS:
                continue
            if str(key).lower() in _REDACT_KEYS:
                record.__dict__[key] = "[REDACTED]"
            else:
                record.__dict__[key] = _scrub_value(val)

        return True


class JSONFormatter(logging.Formatter):
    """Structured JSON to stdout (6.8, 16.1). Never log passwords, tokens,
    Aadhaar, PAN, or bank account numbers — that discipline is on the caller
    (what goes into `extra={...}`), this formatter just serializes it.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Ensure redaction filter has run
        SecretRedactionFilter().filter(record)

        payload: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id and "request_id" not in record.__dict__:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Call once, at startup. DEBUG local only; INFO for business events;
    WARNING for handled anomalies; ERROR for unhandled exceptions and failed
    jobs (16.1).
    """
    root = logging.getLogger()
    root.handlers.clear()
    redaction_filter = SecretRedactionFilter()
    root.addFilter(redaction_filter)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(redaction_filter)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)
