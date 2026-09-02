import logging
import uuid
from collections.abc import Sequence

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger("app")


class AppError(Exception):
    """One error hierarchy, one response shape, no bare HTTPException in
    services (Spec 6.6). Services raise these; main.py's handlers below
    convert them into the standard envelope.
    """

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, details: dict | None = None):
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


def _envelope(code: str, message: str, *, details: dict | None, request_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str:
    # Set by the request-ID middleware (16.2); falls back to a fresh id so
    # this module has no hard import-order dependency on it.
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


# Mirrors app.modules.platform.service._BANNED_DETAIL_KEYS's intent (CLAUDE.md
# rule 10) but is kept local: app/core must not import from app/modules (5.2's
# dependency direction is the other way), and this denylist only ever needs
# to cover request-body field *names*, not the audit log's own key shapes.
_SENSITIVE_FIELD_NAMES = {
    "password",
    "current_password",
    "new_password",
    "otp",
    "token",
    "refresh_token",
    "access_token",
    "aadhaar",
    "aadhaar_number",
    "pan",
    "pan_number",
    "bank_account",
    "bank_account_number",
    "ifsc",
}


def _sanitize_validation_errors(errors: Sequence[dict]) -> list[dict]:
    """Two problems in Pydantic's own `errors()` output, found by actually
    submitting a request that fails a custom validator (a too-short
    password): 1) `ctx.error`, when the failure came from an
    AfterValidator/model_validator raising a plain exception, holds that
    exception OBJECT — not JSON-serializable, so `JSONResponse` crashes
    building the 422 response into an unhandled 500. 2) `input` echoes the
    raw submitted value verbatim — for a password/OTP/token field, this is
    exactly what CLAUDE.md rule 10 ("never log or return passwords, tokens,
    Aadhaar, PAN, or bank details") forbids returning, response body or not.
    """
    sanitized = []
    for err in errors:
        err = dict(err)
        err.pop("ctx", None)
        loc = err.get("loc") or ()
        field = str(loc[-1]) if loc else ""
        if field.lower() in _SENSITIVE_FIELD_NAMES:
            err["input"] = "***redacted***"
        sanitized.append(err)
    return sanitized


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id(request)
        # WARNING for a handled anomaly (a 4xx an app deliberately raised);
        # ERROR with a stack trace for a 5xx AppError (16.1, 6.6). Either way
        # the same request_id that reaches the client also reaches this line.
        log = logger.error if exc.status_code >= 500 else logger.warning
        # `message` is a reserved LogRecord attribute name — passing it via
        # `extra` raises KeyError, so the human text is the log message
        # itself and only the structured fields go in `extra`.
        log(
            exc.message,
            extra={"request_id": request_id, "code": exc.code, "status_code": exc.status_code},
            exc_info=exc.status_code >= 500,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, details=exc.details, request_id=request_id),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _request_id(request)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                "validation_error",
                "The request body failed validation.",
                details={"errors": _sanitize_validation_errors(exc.errors())},
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        request_id = _request_id(request)
        logger.warning(
            "rate_limited",
            extra={"request_id": request_id, "limit": str(exc.limit.limit if exc.limit else None)},
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=_envelope(
                "rate_limited",
                "Too many requests. Please try again later.",
                details=None,
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        request_id = _request_id(request)
        # Never leak SQL or table names in a 4xx message (6.6) — the specific
        # constraint that failed belongs in the log, not the response.
        logger.warning(
            "database_integrity_error",
            extra={"request_id": request_id},
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(
                "conflict",
                "This action conflicts with existing data.",
                details=None,
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        # Every 5xx is logged with the full stack trace, tagged with the same
        # request_id that reaches the client (6.6). Sentry wiring (16.3) is a
        # later work package; this is where it will hook in.
        logger.error(
            "unhandled_exception",
            extra={"request_id": request_id},
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "internal_error",
                "Something went wrong. Please try again.",
                details=None,
                request_id=request_id,
            ),
            headers={"X-Request-ID": request_id},
        )
