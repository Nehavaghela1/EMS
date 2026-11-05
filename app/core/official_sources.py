"""The government sites a statutory rate may cite as its source (5.2).

Every rate row (statutory rate, professional-tax slab, income-tax slab) carries a `source_url`
whose host is on this list: the exact host or a subdomain of it, over https, with no
credentials or port in the link. Anything else (a tax-law publisher, a blog, a look-alike
host such as `epfindia.gov.in.evil.com`) is refused.
"""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

OFFICIAL_HOSTS: tuple[str, ...] = (
    "epfindia.gov.in",
    "pmvbry.epfindia.gov.in",
    "esic.gov.in",
    "labour.gov.in",
    "pib.gov.in",
    "incometaxindia.gov.in",
    "incometax.gov.in",
    "indiabudget.gov.in",
    "egazette.gov.in",
    "commercialtax.gujarat.gov.in",
    "gujarat.gov.in",
)

SOURCE_URL_MESSAGE = "source_url must be an https link to a government site on the official list."


def is_official_url(url: object) -> bool:
    if not isinstance(url, str) or not url or url != url.strip():
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port is not None:
        return False
    host = (parts.hostname or "").lower()
    return any(host == official or host.endswith(f".{official}") for official in OFFICIAL_HOSTS)


def validate_source_url(url: str) -> str:
    """Return the link unchanged, or raise ValueError (never echoes more than the message)."""
    if not is_official_url(url):
        raise ValueError(SOURCE_URL_MESSAGE)
    return url


_LINK = re.compile(r"https?://[^\s,;)\]]+")


def validate_seed_row(row: Mapping[str, Any]) -> None:
    """A seeded row must carry its source (link, title, check date), the link must be
    official, every link inside its note must be official, and no publisher text such as
    TaxGuru may appear. Seeds call this for every row and fail loudly (5.2 rules 4 and 7)."""
    for key in ("source_url", "source_title", "verified_on"):
        if not row.get(key):
            raise ValueError(f"A seeded rate row has no {key}.")
    validate_source_url(row["source_url"])
    note = row.get("source_note") or ""
    for link in _LINK.findall(note):
        if not is_official_url(link):
            raise ValueError(f"A seeded rate note links to a non-official site: {link}")
    if "taxguru" in f"{row['source_url']} {row['source_title']} {note}".lower():
        raise ValueError("A seeded rate row quotes a tax-law publisher.")
