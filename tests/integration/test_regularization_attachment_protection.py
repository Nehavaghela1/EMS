import os
import re
import shutil
import tempfile
import uuid
from datetime import timedelta

import pytest

from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole


def _create_employee(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Test",
        "email": f"{uuid.uuid4().hex[:10]}@attendanceco.com",
        "hire_date": "2024-01-15",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/employees", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _link_user_to_employee(db, company_id, employee_id: str, role: UserRole) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@attendanceco.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    employee.user_id = user.id
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clean_test_uploads(monkeypatch):
    """Ensure all uploads in this test go to a temporary directory and are cleaned up."""
    temp_dir = tempfile.mkdtemp(prefix="reg_test_uploads_")
    monkeypatch.setattr(
        "app.modules.time_leave.router.get_regularizations_upload_dir",
        lambda: temp_dir,
        raising=False,
    )
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_regularization_attachment_protection(client, company_a, company_b, db):
    # Setup reporting hierarchy:
    # mgr_chain -> req_emp
    mgr_chain = _create_employee(client, company_a.hr_headers)
    mgr_chain_headers = _link_user_to_employee(
        db, company_a.company_id, mgr_chain["id"], UserRole.manager
    )

    req_emp = _create_employee(client, company_a.hr_headers, reporting_manager_id=mgr_chain["id"])
    req_headers = _link_user_to_employee(db, company_a.company_id, req_emp["id"], UserRole.employee)

    mgr_out = _create_employee(client, company_a.hr_headers)
    mgr_out_headers = _link_user_to_employee(
        db, company_a.company_id, mgr_out["id"], UserRole.manager
    )

    unrelated_emp = _create_employee(client, company_a.hr_headers)
    unrelated_headers = _link_user_to_employee(
        db, company_a.company_id, unrelated_emp["id"], UserRole.employee
    )

    # 1. Requester checks in and regularizes with attachment
    in_time = (utcnow() - timedelta(hours=9)).isoformat()
    out_time = utcnow().isoformat()
    created = client.post("/api/v1/attendance/check-in", headers=req_headers).json()

    files = {"attachment": ("proof document.pdf", b"proof content 123", "application/pdf")}
    data = {
        "check_in": in_time,
        "check_out": out_time,
        "reason": "Forgot punch out",
    }
    req_resp = client.post(
        f"/api/v1/attendance/{created['id']}/regularize",
        headers=req_headers,
        data=data,
        files=files,
    )
    assert req_resp.status_code == 200, req_resp.text
    attachment_url = req_resp.json()["attachment_url"]
    filename = attachment_url.split("/")[-1]

    # Required assertions:
    # 1. no token -> 401
    res_no_token = client.get(attachment_url)
    assert res_no_token.status_code == 401, f"Expected 401, got {res_no_token.status_code}"

    # 2. unrelated employee -> 403
    res_unrelated = client.get(attachment_url, headers=unrelated_headers)
    assert res_unrelated.status_code == 403, f"Expected 403, got {res_unrelated.status_code}"

    # 3. the requester -> 200
    res_req = client.get(attachment_url, headers=req_headers)
    assert res_req.status_code == 200, f"Expected 200, got {res_req.status_code}"
    assert res_req.content == b"proof content 123"

    # 4. manager in the reporting chain -> 200
    res_mgr_in = client.get(attachment_url, headers=mgr_chain_headers)
    assert res_mgr_in.status_code == 200, f"Expected 200, got {res_mgr_in.status_code}"

    # 5. manager outside the chain -> 403
    res_mgr_out = client.get(attachment_url, headers=mgr_out_headers)
    assert res_mgr_out.status_code == 403, f"Expected 403, got {res_mgr_out.status_code}"

    # 6. HR -> 200
    res_hr = client.get(attachment_url, headers=company_a.hr_headers)
    assert res_hr.status_code == 200, f"Expected 200, got {res_hr.status_code}"

    # 7. another company's HR -> 404
    res_b_hr = client.get(attachment_url, headers=company_b.hr_headers)
    assert res_b_hr.status_code == 404, f"Expected 404, got {res_b_hr.status_code}"

    # 8. unknown filename -> 404
    res_unknown = client.get(
        "/api/v1/attendance/regularizations/attachments/does-not-exist.pdf",
        headers=company_a.hr_headers,
    )
    assert res_unknown.status_code == 404, f"Expected 404, got {res_unknown.status_code}"

    # 9. a filename with "..", encoded slashes or backslashes -> never 200
    res_dotdot = client.get(
        f"/api/v1/attendance/regularizations/attachments/..%2f{filename}",
        headers=company_a.hr_headers,
    )
    assert res_dotdot.status_code != 200, f"Expected non-200, got {res_dotdot.status_code}"

    res_slash = client.get(
        f"/api/v1/attendance/regularizations/attachments/sub%2f{filename}",
        headers=company_a.hr_headers,
    )
    assert res_slash.status_code != 200, f"Expected non-200, got {res_slash.status_code}"

    res_backslash = client.get(
        f"/api/v1/attendance/regularizations/attachments/sub\\{filename}",
        headers=company_a.hr_headers,
    )
    assert res_backslash.status_code != 200, f"Expected non-200, got {res_backslash.status_code}"


def test_upload_traversal_filename_sanitized(client, company_a, db, clean_test_uploads):
    """Upload with filename '../../x.png' stores the file inside the upload dir with a safe name."""
    req_emp = _create_employee(client, company_a.hr_headers)
    req_headers = _link_user_to_employee(db, company_a.company_id, req_emp["id"], UserRole.employee)

    created = client.post("/api/v1/attendance/check-in", headers=req_headers).json()
    files = {"attachment": ("../../x.png", b"fake png data", "image/png")}
    data = {
        "check_in": (utcnow() - timedelta(hours=8)).isoformat(),
        "check_out": utcnow().isoformat(),
        "reason": "Traverse test",
    }
    req_resp = client.post(
        f"/api/v1/attendance/{created['id']}/regularize",
        headers=req_headers,
        data=data,
        files=files,
    )
    assert req_resp.status_code == 200, req_resp.text
    attachment_url = req_resp.json()["attachment_url"]
    filename = attachment_url.split("/")[-1]

    # Verify safe name properties
    assert ".." not in filename
    assert "/" not in filename
    assert "\\" not in filename
    assert "x.png" in filename
    # Sanitize rule: only A-Z a-z 0-9 . _ -
    safe_pattern = r"^[a-f0-9\-]+_[a-zA-Z0-9._\-]+$"
    assert re.match(safe_pattern, filename), f"Filename {filename} does not match safe pattern"

    # Stored on disk inside upload_dir
    upload_dir = clean_test_uploads
    stored_path = os.path.join(upload_dir, filename)
    assert os.path.isfile(stored_path)
    with open(stored_path, "rb") as f:
        assert f.read() == b"fake png data"
