"""Red-first tests for PART G: PAN and GSTIN masking and explicit reveal.

Rules:
1. An hr_admin reading their own company gets a masked PAN and GSTIN.
2. A super admin listing companies gets masked values by default.
3. A super admin's explicit reveal returns the full value and writes an audit row.
4. A company user's attempt to reveal returns 403.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.identity.models import Company, UserRole
from app.modules.platform.models import AuditLog
from tests.conftest import TenantContext, _make_user_headers


def test_hr_admin_reading_own_company_gets_masked_pan_and_gstin(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    # Set known PAN and GSTIN on company_a
    comp = db.get(Company, company_a.company_id)
    assert comp is not None
    comp.pan_number = "AAACA1234A"
    comp.gst_number = "24AAACA1234A1Z5"
    db.commit()

    resp = client.get("/api/v1/companies/me", headers=company_a.hr_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pan_number"] == "•••••••34A"
    assert data["gst_number"] == "••••••••••••1Z5"


def test_super_admin_listing_companies_gets_masked_values_by_default(
    client: TestClient, db: Session, company_a: TenantContext, super_admin_headers: dict[str, str]
) -> None:
    comp = db.get(Company, company_a.company_id)
    assert comp is not None
    comp.pan_number = "AAACA1234A"
    comp.gst_number = "24AAACA1234A1Z5"
    db.commit()

    # List companies
    resp = client.get("/api/v1/companies", headers=super_admin_headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    target = next((c for c in items if c["id"] == str(company_a.company_id)), None)
    assert target is not None
    assert target["pan_number"] == "•••••••34A"
    assert target["gst_number"] == "••••••••••••1Z5"

    # Detail by default without reveal
    resp_detail = client.get(
        f"/api/v1/companies/{company_a.company_id}", headers=super_admin_headers
    )
    assert resp_detail.status_code == 200, resp_detail.text
    detail = resp_detail.json()
    assert detail["pan_number"] == "•••••••34A"
    assert detail["gst_number"] == "••••••••••••1Z5"


def test_super_admin_explicit_reveal_returns_full_value_and_writes_audit_row(
    client: TestClient, db: Session, company_a: TenantContext, super_admin_headers: dict[str, str]
) -> None:
    comp = db.get(Company, company_a.company_id)
    assert comp is not None
    comp.pan_number = "AAACA1234A"
    comp.gst_number = "24AAACA1234A1Z5"
    db.commit()

    # Query with reveal=true
    resp = client.get(
        f"/api/v1/companies/{company_a.company_id}?reveal=true", headers=super_admin_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pan_number"] == "AAACA1234A"
    assert data["gst_number"] == "24AAACA1234A1Z5"

    # Verify audit row was written
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == company_a.company_id,
            AuditLog.action == "COMPANY_TAX_ID_REVEALED",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["fields"] == ["pan_number", "gst_number"]


def test_company_user_attempt_to_reveal_returns_403(
    client: TestClient, db: Session, company_a: TenantContext
) -> None:
    # hr_admin trying to call reveal on company detail endpoint (which is super admin only)
    resp = client.get(
        f"/api/v1/companies/{company_a.company_id}?reveal=true", headers=company_a.hr_headers
    )
    assert resp.status_code == 403

    # owner trying to call reveal
    owner_headers = _make_user_headers(db, company_a.company_id, UserRole.owner)
    resp_owner = client.get(
        f"/api/v1/companies/{company_a.company_id}?reveal=true", headers=owner_headers
    )
    assert resp_owner.status_code == 403
