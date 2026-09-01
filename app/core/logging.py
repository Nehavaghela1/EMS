import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

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


class JSONFormatter(logging.Formatter):
    """Structured JSON to stdout (6.8, 16.1). Never log passwords, tokens,
    Aadhaar, PAN, or bank account numbers — that discipline is on the caller
    (what goes into `extra={...}`), this formatter just serializes it.
    """

    def format(self, record: logging.LogRecord) -> str:
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
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)
