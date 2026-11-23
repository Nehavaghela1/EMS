"""Tests for PART H: Reject raw HTML in company name at registration."""

from fastapi.testclient import TestClient


def test_company_registration_rejects_html_in_company_name(client: TestClient) -> None:
    bad_names = [
        "<img src=x onerror=alert(1)> QA XSS Co",
        "Acme <b>Corp</b>",
        "<script>alert('xss')</script>",
        "Acme > Tech",
        "Acme < Tech",
    ]
    for name in bad_names:
        resp = client.post(
            "/api/v1/companies/register",
            json={
                "company_name": name,
                "company_email": "xss-test@example.com",
                "phone": "+91 9876543210",
                "industry": "Technology",
                "address": "123 Tech Park",
                "pan_number": "AAACA1234A",
            },
        )
        assert resp.status_code == 422, (
            f"Expected 422 for name {name}, got {resp.status_code}: {resp.text}"
        )
        assert "<" in resp.text or "HTML" in resp.text or "characters" in resp.text
