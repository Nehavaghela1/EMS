"""The page fetcher of the scheduled rate-source check (5.9).

It reads one government page and returns its text. It never reads numbers out of the page:
version 1 only notices that the page CHANGED (the SHA-256 of the normalised text differs) and a
person types the numbers. A per-source extractor can be registered later in `EXTRACTORS`
(`name`, `can_handle(source)`, `extract(page_text)`); none is registered today.

Limits, all enforced here: https only; only hosts on the government allow-list, re-checked after
EVERY redirect (at most 3); a 15 second timeout; a 2 MB cap; no cookies; the fixed user agent
`EMS-Pro-RateCheck`; text, html or pdf content types only.
"""

import hashlib
import html
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx

from app.core.official_sources import is_official_url


class FetchError(Exception):
    """The page could not be read. The message is safe to store and to show: it never carries
    page text."""


@dataclass(frozen=True)
class FetchedPage:
    text: str
    content_type: str


class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...


class PageExtractor(Protocol):
    """Reads proposed numbers out of a page of one known source. None is registered in v1."""

    name: str

    def can_handle(self, source: Any) -> bool: ...

    def extract(self, page_text: str) -> dict[str, Any] | None: ...


EXTRACTORS: list[PageExtractor] = []


def find_extractor(source: Any) -> PageExtractor | None:
    return next((e for e in EXTRACTORS if e.can_handle(source)), None)


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class OfficialPageFetcher:
    USER_AGENT = "EMS-Pro-RateCheck"
    MAX_BYTES = 2 * 1024 * 1024
    MAX_REDIRECTS = 3

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.timeout_seconds = 15
        self._transport = transport

    def fetch(self, url: str) -> FetchedPage:
        current = url
        try:
            with httpx.Client(
                transport=self._transport, timeout=self.timeout_seconds, follow_redirects=False
            ) as client:
                for hop in range(self.MAX_REDIRECTS + 1):
                    if not is_official_url(current):
                        raise FetchError("The page is not an https page on the official list.")
                    client.cookies.clear()  # no cookie is ever sent, not even one a hop set
                    with client.stream(
                        "GET", current, headers={"User-Agent": self.USER_AGENT}
                    ) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location or hop == self.MAX_REDIRECTS:
                                raise FetchError("The page redirected too many times.")
                            current = urljoin(current, location)
                            continue
                        return self._read(response)
        except httpx.HTTPError:
            raise FetchError("The page could not be reached.") from None
        raise FetchError("The page redirected too many times.")  # pragma: no cover

    def _read(self, response: httpx.Response) -> FetchedPage:
        if response.status_code != 200:
            raise FetchError(f"The page answered with status {response.status_code}.")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if not (content_type.startswith("text/") or content_type == "application/pdf"):
            raise FetchError("The page is not text, html or pdf.")
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > self.MAX_BYTES:
                raise FetchError("The page is larger than 2 MB.")
        return FetchedPage(text=body.decode("utf-8", errors="replace"), content_type=content_type)


_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def normalize_page_text(raw: str) -> str:
    """Scripts, styles, comments and tags removed, entities decoded, whitespace collapsed:
    a change in markup or layout alone does not change the hash."""
    text = _SCRIPT_OR_STYLE.sub(" ", raw)
    text = _COMMENT.sub(" ", text)
    text = _TAG.sub(" ", text)
    return _SPACE.sub(" ", html.unescape(text)).strip()


def content_hash(raw: str) -> str:
    return hashlib.sha256(normalize_page_text(raw).encode("utf-8")).hexdigest()
