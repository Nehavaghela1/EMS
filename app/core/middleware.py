import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.audit_context import (
    AuditContext,
    audit_context_var,
    parse_audit_ip,
    parse_audit_request_id,
    parse_audit_user_agent,
)
from app.core.config import settings
from app.core.logging import request_id_var
from app.core.rate_limit import get_client_ip


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Read X-Request-ID from the request or generate one, put it in a context
    variable available to every log call, and return it in the response
    header and in every error envelope (16.2).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """A small set of headers on every response (9.8)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Sets ContextVar-based audit context for the request lifecycle."""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw_ip = get_client_ip(request)
        raw_ua = request.headers.get("user-agent")
        raw_req_id = getattr(request.state, "request_id", None) or request.headers.get(
            "X-Request-ID"
        )

        ctx = AuditContext(
            ip_address=parse_audit_ip(raw_ip),
            user_agent=parse_audit_user_agent(raw_ua),
            request_id=parse_audit_request_id(raw_req_id),
        )
        token = audit_context_var.set(ctx)
        try:
            return await call_next(request)
        finally:
            audit_context_var.reset(token)
