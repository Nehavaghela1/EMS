"""Small field validators shared by more than one module's schemas.

Each function takes the raw value and returns the cleaned value, or raises
ValueError with a message the user can act on (Pydantic turns it into a 422).
"""

import re

# Digits, spaces, and the punctuation people really type in phone numbers.
_PHONE_ALLOWED = re.compile(r"^\+?[0-9 ()\-.]+$")
_PINCODE = re.compile(r"^[A-Za-z0-9 \-]{3,10}$")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

PHONE_MAX_LENGTH = 20
PHONE_MIN_DIGITS = 6
LOGO_URL_MAX_LENGTH = 2048
# The branding screen stores small logos inline as base64 image data URLs.
# 700,000 base64 characters is about 512 KB of image.
LOGO_DATA_URL_MAX_LENGTH = 700_000
# No SVG: it is executable content, and a blocklist cannot make it safe.
_LOGO_DATA_URL = re.compile(
    r"^data:image/(png|jpeg|jpg|webp);base64,[A-Za-z0-9+/]+={0,2}$",
    re.IGNORECASE,
)


def clean_phone(v: str | None) -> str | None:
    """Optional phone: blank becomes None; otherwise digits with an optional
    leading +, spaces, brackets, dots or hyphens, 6+ digits, max 20 chars."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Phone must be text.")
    s = v.strip()
    if not s:
        return None
    if len(s) > PHONE_MAX_LENGTH:
        raise ValueError(f"Phone must be at most {PHONE_MAX_LENGTH} characters.")
    if not _PHONE_ALLOWED.match(s) or sum(c.isdigit() for c in s) < PHONE_MIN_DIGITS:
        raise ValueError(
            "Phone may contain only digits, spaces, brackets, hyphens and a leading +,"
            f" with at least {PHONE_MIN_DIGITS} digits."
        )
    return s


def clean_pincode(v: str | None) -> str | None:
    """Optional postal code. For India (the default market) it must be 6 digits;
    other formats are 3-10 letters, digits, spaces or hyphens with at least one
    digit, so a value like 'ABCDE' is rejected."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Pincode must be text.")
    s = v.strip()
    if not s:
        return None
    if not _PINCODE.match(s) or not any(c.isdigit() for c in s):
        raise ValueError("Pincode must be 3-10 characters and contain digits.")
    return s


def clean_logo_url(v: str | None) -> str | None:
    """Company logo: an https URL, an app-relative path, or a small PNG, JPEG
    or WebP image as a base64 data URL (max about 512 KB). Any other data URL,
    javascript: and other schemes are refused."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Logo URL must be text.")
    s = v.strip()
    if not s:
        return None
    if s.lower().startswith("data:"):
        if len(s) > LOGO_DATA_URL_MAX_LENGTH:
            raise ValueError("Logo image must be smaller than 512 KB.")
        if not _LOGO_DATA_URL.match(s):
            raise ValueError("Logo image must be a PNG, JPEG or WebP picture.")
        return s
    if len(s) > LOGO_URL_MAX_LENGTH:
        raise ValueError(f"Logo URL must be at most {LOGO_URL_MAX_LENGTH} characters.")
    if any(ch.isspace() or ord(ch) < 32 for ch in s):
        raise ValueError("Logo URL must not contain spaces or control characters.")
    if s.lower().startswith("https://"):
        return s
    if s.startswith("/") and not s.startswith("//") and "\\" not in s:
        return s
    raise ValueError("Logo must be an https:// URL or a PNG, JPEG or WebP image.")


def clean_hex_color(v: str | None) -> str | None:
    """Optional '#RRGGBB' colour, stored lower-case."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Colour must be text.")
    s = v.strip()
    if not s:
        return None
    if not _HEX_COLOR.match(s):
        raise ValueError("Colour must be a hex value like #2563eb.")
    return s.lower()
