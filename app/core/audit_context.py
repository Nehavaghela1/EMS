"""Audit logging request context (Spec 7.8, WP 3.5).
Provides ContextVar-based propagation of ip_address, user_agent, and request_id
from the incoming HTTP request to AuditService.record.
"""

import ipaddress
import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditContext:
    ip_address: str | None
    user_agent: str | None
    request_id: uuid.UUID | None


audit_context_var: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)


def parse_audit_ip(raw_ip: str | None) -> str | None:
    """Parses and normalizes IP address. Returns string or None if invalid."""
    if not raw_ip or not isinstance(raw_ip, str):
        return None
    cleaned = raw_ip.strip()
    if not cleaned:
        return None
    try:
        ip = ipaddress.ip_address(cleaned)
        return str(ip)
    except ValueError:
        return None


def parse_audit_user_agent(raw_ua: str | None) -> str | None:
    """Truncates user agent string to at most 500 characters or None."""
    if not raw_ua or not isinstance(raw_ua, str):
        return None
    cleaned = raw_ua.strip()
    return cleaned[:500] if cleaned else None


def parse_audit_request_id(raw_req_id: str | uuid.UUID | None) -> uuid.UUID | None:
    """Parses request ID into a valid UUID object or None."""
    if raw_req_id is None:
        return None
    if isinstance(raw_req_id, uuid.UUID):
        return raw_req_id
    if not isinstance(raw_req_id, str):
        return None
    cleaned = raw_req_id.strip()
    try:
        return uuid.UUID(cleaned)
    except (ValueError, TypeError, AttributeError):
        return None
