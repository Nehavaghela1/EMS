"""Sentry error tracking configuration and custom sensitive data scrubber.

Rules:
- R1: Wire Sentry behind settings.SENTRY_DSN, off when absent so dev and tests are unaffected.
- R2: Custom scrubber removing password, token, Aadhaar, PAN, bank account,
      authorization header, cookies, etc.
- R3: Tag events with company_id and request_id, never employee name or email.
"""

import re
from typing import Any

from app.core.config import settings

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "activation_token",
    "reset_token",
    "aadhaar",
    "aadhaar_number",
    "pan",
    "pan_number",
    "bank_account",
    "account_number",
    "account_number_enc",
    "authorization",
    "cookie",
    "set-cookie",
    "secret",
}

# Regex patterns for values (e.g. Bearer tokens, Aadhaar 12-digit, PAN 10-char, typical bank acc)
RE_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE)
RE_AADHAAR = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")
RE_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)


def scrub_data(data: Any) -> Any:
    """Recursively scrub sensitive keys and string patterns from payloads."""
    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            k_lower = str(k).lower().strip()
            if any(s in k_lower for s in SENSITIVE_KEYS):
                scrubbed[k] = "[SCRUBBED]"
            else:
                scrubbed[k] = scrub_data(v)
        return scrubbed
    elif isinstance(data, list):
        return [scrub_data(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(scrub_data(item) for item in data)
    elif isinstance(data, str):
        # Scrub Bearer tokens in headers
        res = RE_BEARER.sub("Bearer [SCRUBBED]", data)
        # Scrub Aadhaar in free text
        res = RE_AADHAAR.sub("[SCRUBBED_AADHAAR]", res)
        # Scrub PAN in free text
        res = RE_PAN.sub("[SCRUBBED_PAN]", res)
        return res
    return data


def sentry_before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub sensitive data and enforce user anonymization before sending to Sentry."""
    # 1. Scrub request headers, cookies, and body data if present
    if "request" in event:
        req = event["request"]
        if "headers" in req:
            req["headers"] = scrub_data(req["headers"])
        if "cookies" in req:
            req["cookies"] = "[SCRUBBED]"
        if "data" in req:
            req["data"] = scrub_data(req["data"])

    # 2. Scrub extra and context payloads
    if "extra" in event:
        event["extra"] = scrub_data(event["extra"])
    if "contexts" in event:
        event["contexts"] = scrub_data(event["contexts"])

    # 3. Strip any identifying user data (name, email) - keep only company_id/id if safe
    if "user" in event:
        user_info = event["user"]
        # Never let name or email leave the process
        user_info.pop("email", None)
        user_info.pop("username", None)
        user_info.pop("name", None)

    return event


def init_sentry() -> bool:
    """Initialize Sentry SDK if SENTRY_DSN is present. Return True if initialized."""
    dsn = getattr(settings, "SENTRY_DSN", None)
    if not dsn:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=getattr(settings, "ENVIRONMENT", "production"),
        before_send=sentry_before_send,  # type: ignore[arg-type]
        send_default_pii=False,  # type: ignore[call-arg]
    )
    return True
