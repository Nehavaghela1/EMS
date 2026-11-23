# ruff: noqa: F401, F811  (pytest fixtures imported from a sibling test module)
"""Module 3 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-025  a file of exactly 25 MB is accepted (the early Content-Length check
         counted the multipart wrapper as part of the file)
BUG-095  notification links point at pages that exist in the app
"""

import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.rules.test_3_3_files import _auth_headers, files_setup

LIMIT = 25 * 1024 * 1024


def test_file_of_exactly_25_mb_is_accepted(client: TestClient, files_setup: dict[str, Any]) -> None:
    headers = _auth_headers(files_setup["emp1_user"])
    body = b"%PDF-1.4 " + b"A" * (LIMIT - 9)
    assert len(body) == LIMIT
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("exact.pdf", body, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text[:200]


def test_file_one_byte_over_25_mb_is_refused(
    client: TestClient, files_setup: dict[str, Any]
) -> None:
    headers = _auth_headers(files_setup["emp1_user"])
    body = b"%PDF-1.4 " + b"A" * (LIMIT - 8)
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("over.pdf", body, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 413


def test_every_hard_coded_notification_link_is_a_real_app_page() -> None:
    router = Path("frontend/src/app/router.tsx").read_text()
    routes = set(re.findall(r'path="(/[^"]*)"', router))
    sources = "\n".join(
        p.read_text()
        for p in list(Path("app/modules").rglob("*.py")) + list(Path("app/workers").rglob("*.py"))
    )
    links = set(re.findall(r'action_url="(/[^"]+)"', sources))
    links |= set(re.findall(r'_PAGE_URL = "(/[^"]+)"', sources))
    assert links, "no notification links found"
    for link in links:
        assert link in routes, f"{link} is not a frontend route"
