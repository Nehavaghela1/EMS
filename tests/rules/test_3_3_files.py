"""Rules test suite for 3.3 Files and vault contracts (F1-F8).
Verifies file access permissions, employee doc exclusions, upload validation,
storage path containment, signed link lifetimes, download headers, audit logging,
and rate limits.
"""

import hashlib
import hmac
import inspect
import io
import os
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog, EmployeeDocument, FileObject
from app.modules.projects.models import Project, ProjectDocument, ProjectMember


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=str(user.id),
        company_id=str(user.company_id),
        role=user.role.value,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_sample_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    )


def _make_sample_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00"


def _make_sample_docx() -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("word/document.xml", "<w:document></w:document>")
    return bio.getvalue()


@pytest.fixture
def files_setup(db: Session, tmp_path, monkeypatch) -> dict[str, Any]:
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_root))

    # Company 1
    cid1 = uuid.uuid4()
    c1 = Company(
        id=cid1,
        name=f"Files Corp {uuid.uuid4().hex[:6]}",
        code=f"FC{uuid.uuid4().hex[:4].upper()}",
        email=f"fc1-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(c1)
    db.flush()

    owner1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"owner1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner1)
    db.flush()
    c1.owner_user_id = owner1.id
    db.flush()

    hr1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"hr1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr1)

    sa1 = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"sa1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.super_admin,
        is_active=True,
    )
    db.add(sa1)
    db.flush()

    bind_tenant_to_session(db, company_id=cid1, is_platform_admin=True)

    mgr1_user = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"mgr1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(mgr1_user)
    db.flush()

    mgr1_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid1,
        user_id=mgr1_user.id,
        employee_code=f"EMP-MGR-{uuid.uuid4().hex[:4].upper()}",
        first_name="Manager",
        last_name="One",
        email=mgr1_user.email,
        hire_date=datetime.now(UTC).date(),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
    )
    db.add(mgr1_emp)

    emp1_user = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"emp1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(emp1_user)
    db.flush()

    emp1_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid1,
        user_id=emp1_user.id,
        employee_code=f"EMP-1-{uuid.uuid4().hex[:4].upper()}",
        first_name="Employee",
        last_name="One",
        email=emp1_user.email,
        hire_date=datetime.now(UTC).date(),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
    )
    db.add(emp1_emp)

    emp2_user = User(
        id=uuid.uuid4(),
        company_id=cid1,
        email=f"emp2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(emp2_user)
    db.flush()

    emp2_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid1,
        user_id=emp2_user.id,
        employee_code=f"EMP-2-{uuid.uuid4().hex[:4].upper()}",
        first_name="Employee",
        last_name="Two",
        email=emp2_user.email,
        hire_date=datetime.now(UTC).date(),
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
    )
    db.add(emp2_emp)

    # Company 2
    cid2 = uuid.uuid4()
    c2 = Company(
        id=cid2,
        name=f"Files Corp Two {uuid.uuid4().hex[:6]}",
        code=f"FC2{uuid.uuid4().hex[:4].upper()}",
        email=f"fc2-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(c2)
    db.flush()

    owner2 = User(
        id=uuid.uuid4(),
        company_id=cid2,
        email=f"owner2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add(owner2)
    db.flush()
    c2.owner_user_id = owner2.id

    hr2 = User(
        id=uuid.uuid4(),
        company_id=cid2,
        email=f"hr2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr2)
    db.commit()
    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)

    return {
        "upload_root": upload_root,
        "company1": c1,
        "owner1": owner1,
        "hr1": hr1,
        "sa1": sa1,
        "mgr1_user": mgr1_user,
        "mgr1_emp": mgr1_emp,
        "emp1_user": emp1_user,
        "emp1_emp": emp1_emp,
        "emp2_user": emp2_user,
        "emp2_emp": emp2_emp,
        "company2": c2,
        "owner2": owner2,
        "hr2": hr2,
    }


# ── F1: Download link access checks ───────────────────────────────────────


def test_f1_link_access_uploader_and_hr_level(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """F1: A download link is issued only to the uploader, HR-level of same company,
    or someone who can see the attached record. Unrelated users get 404 (same as missing).
    """
    emp1_user = files_setup["emp1_user"]
    hr1 = files_setup["hr1"]
    owner1 = files_setup["owner1"]
    sa1 = files_setup["sa1"]
    emp2_user = files_setup["emp2_user"]

    # Upload file as emp1
    upload_res = client.post(
        "/api/v1/files/upload",
        files={"file": ("report.pdf", b"%PDF-1.4 sample content", "application/pdf")},
        headers=_auth_headers(emp1_user),
    )
    assert upload_res.status_code == 201
    file_id = upload_res.json()["file_object_id"]

    # 1. Uploader (emp1) can request link -> 200
    res_uploader = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(emp1_user))
    assert res_uploader.status_code == 200
    assert "signature=" in res_uploader.json()["url"]

    # 2. HR Admin of same company can request link -> 200
    res_hr = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr1))
    assert res_hr.status_code == 200

    # 3. Owner of same company can request link -> 200
    res_owner = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(owner1))
    assert res_owner.status_code == 200

    # 4. Super Admin of same company can request link -> 200
    res_sa = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(sa1))
    assert res_sa.status_code == 200

    # 5. Unrelated employee of same company gets 404 (same as missing)
    res_unauth = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(emp2_user))
    assert res_unauth.status_code == 404
    assert res_unauth.json()["error"]["code"] == "not_found"

    # 6. Non-existent file id gives same 404
    missing_id = uuid.uuid4()
    res_missing = client.get(f"/api/v1/files/{missing_id}/url", headers=_auth_headers(emp1_user))
    assert res_missing.status_code == 404
    assert res_missing.json()["error"]["code"] == "not_found"


def test_f1_link_access_project_member_and_manager(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """F1: If file is attached to a project document, a project member or project manager
    can request the link even if they are not the uploader. Non-members get 404.
    """
    c1 = files_setup["company1"]
    hr1 = files_setup["hr1"]
    mgr1_emp = files_setup["mgr1_emp"]
    mgr1_user = files_setup["mgr1_user"]
    emp1_emp = files_setup["emp1_emp"]
    emp1_user = files_setup["emp1_user"]
    emp2_user = files_setup["emp2_user"]

    # HR uploads a project specification file
    upload_res = client.post(
        "/api/v1/files/upload",
        files={"file": ("project_spec.pdf", b"%PDF-1.4 spec content", "application/pdf")},
        headers=_auth_headers(hr1),
    )
    assert upload_res.status_code == 201
    file_id = uuid.UUID(upload_res.json()["file_object_id"])

    # Create project with mgr1 as manager
    bind_tenant_to_session(db, company_id=c1.id, is_platform_admin=True)
    project = Project(
        id=uuid.uuid4(),
        company_id=c1.id,
        name="Apollo Project",
        code=f"APO-{uuid.uuid4().hex[:4].upper()}",
        status="active",
        manager_id=mgr1_emp.id,
    )
    db.add(project)
    db.flush()

    # Add emp1 as project member (emp2 is NOT a member)
    member = ProjectMember(
        id=uuid.uuid4(),
        company_id=c1.id,
        project_id=project.id,
        employee_id=emp1_emp.id,
        role="member",
    )
    db.add(member)

    # Attach file as ProjectDocument
    pdoc = ProjectDocument(
        id=uuid.uuid4(),
        company_id=c1.id,
        project_id=project.id,
        file_id=file_id,
        name="Apollo Spec.pdf",
        file_size=len(b"%PDF-1.4 spec content"),
        file_type="application/pdf",
        uploaded_by=hr1.id,
    )
    db.add(pdoc)
    db.commit()

    # 1. Project Member (emp1) can access -> 200
    res_member = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(emp1_user))
    assert res_member.status_code == 200

    # 2. Project Manager (mgr1) can access -> 200
    res_mgr = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(mgr1_user))
    assert res_mgr.status_code == 200

    # 3. Other employee (emp2) not on project gets 404
    res_non_member = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(emp2_user))
    assert res_non_member.status_code == 404


# ── F2: Employee document generic link exclusion ──────────────────────────


def test_f2_employee_document_generic_link_excluded(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """F2: A file attached to an employee document never opens through the generic link (404);
    only through the employee documents routes.
    """
    c1 = files_setup["company1"]
    hr1 = files_setup["hr1"]
    emp1_emp = files_setup["emp1_emp"]

    upload_res = client.post(
        "/api/v1/files/upload",
        files={"file": ("aadhaar.pdf", b"%PDF-1.4 aadhaar content", "application/pdf")},
        headers=_auth_headers(hr1),
    )
    assert upload_res.status_code == 201
    file_id = uuid.UUID(upload_res.json()["file_object_id"])

    # Attach to EmployeeDocument
    bind_tenant_to_session(db, company_id=c1.id, is_platform_admin=True)
    emp_doc = EmployeeDocument(
        id=uuid.uuid4(),
        company_id=c1.id,
        employee_id=emp1_emp.id,
        file_object_id=file_id,
        document_type="national_id",
        name="Aadhaar Card.pdf",
    )
    db.add(emp_doc)
    db.commit()

    # Calling /files/{file_id}/url must return 404 even for the uploader / HR
    res = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr1))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# ── F3: Upload validation and size limits ──────────────────────────────────


def test_f3_upload_validation_and_allowed_types(
    client: TestClient, files_setup: dict[str, Any]
) -> None:
    """F3: Upload accepts safe filenames, allowed types only (PDF, JPG, JPEG, PNG, DOCX)
    verified by name and magic bytes; unsupported types or empty files return 422.
    """
    emp1 = files_setup["emp1_user"]
    emp_headers = _auth_headers(emp1)

    # 1. Valid PDF
    r_pdf = client.post(
        "/api/v1/files/upload",
        files={"file": ("doc.pdf", b"%PDF-1.4 pdf data", "application/pdf")},
        headers=emp_headers,
    )
    assert r_pdf.status_code == 201

    # 2. Valid PNG
    r_png = client.post(
        "/api/v1/files/upload",
        files={"file": ("image.png", _make_sample_png(), "image/png")},
        headers=emp_headers,
    )
    assert r_png.status_code == 201

    # 3. Valid JPEG
    r_jpg = client.post(
        "/api/v1/files/upload",
        files={"file": ("photo.jpg", _make_sample_jpeg(), "image/jpeg")},
        headers=emp_headers,
    )
    assert r_jpg.status_code == 201

    # 4. Valid DOCX
    r_docx = client.post(
        "/api/v1/files/upload",
        files={"file": ("resume.docx", _make_sample_docx(), "application/vnd.docx")},
        headers=emp_headers,
    )
    assert r_docx.status_code == 201

    # 5. Disallowed extension: text/plain
    r_txt = client.post(
        "/api/v1/files/upload",
        files={"file": ("notes.txt", b"plain text notes", "text/plain")},
        headers=emp_headers,
    )
    assert r_txt.status_code == 422
    assert r_txt.json()["error"]["code"] == "validation_error"

    # 6. Disallowed extension: executable .sh
    r_sh = client.post(
        "/api/v1/files/upload",
        files={"file": ("script.sh", b"echo evil", "application/x-sh")},
        headers=emp_headers,
    )
    assert r_sh.status_code == 422

    # 7. Content mismatch: extension is .pdf but content is random text
    r_mismatch = client.post(
        "/api/v1/files/upload",
        files={"file": ("fake.pdf", b"this is not a pdf file", "application/pdf")},
        headers=emp_headers,
    )
    assert r_mismatch.status_code == 422

    # 8. Empty file: 422
    r_empty = client.post(
        "/api/v1/files/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers=emp_headers,
    )
    assert r_empty.status_code == 422


def test_f3_upload_size_limit_25mb(client: TestClient, files_setup: dict[str, Any]) -> None:
    """F3: Upload larger than 25 MB gives 413 PayloadTooLargeError, checked while reading."""
    emp1 = files_setup["emp1_user"]
    emp_headers = _auth_headers(emp1)

    # 25 MB + 1 byte
    oversized = b"%PDF-1.4 " + (b"A" * (25 * 1024 * 1024))
    r_large = client.post(
        "/api/v1/files/upload",
        files={"file": ("huge.pdf", oversized, "application/pdf")},
        headers=emp_headers,
    )
    assert r_large.status_code == 413
    assert r_large.json()["error"]["code"] == "file_too_large"


# ── F4: Storage path safety and response shape ────────────────────────────


def test_f4_storage_path_safety_and_response_shape(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """F4: File is stored under a random id with a safe extension in the company folder;
    the client's file name never goes into the disk path and disk path is never shown in reply.
    """
    emp1 = files_setup["emp1_user"]
    emp_headers = _auth_headers(emp1)
    upload_root = files_setup["upload_root"]

    raw_client_name = "test_upload_contract_doc.pdf"
    r = client.post(
        "/api/v1/files/upload",
        files={"file": (raw_client_name, b"%PDF-1.4 sanitized name test", "application/pdf")},
        headers=emp_headers,
    )
    assert r.status_code == 201
    data = r.json()

    # 1. Response shape contains expected safe keys and NO disk path
    assert "file_object_id" in data
    assert "file_name" in data
    assert "file_type" in data
    assert "file_size" in data
    assert "storage_path" not in data
    assert "path" not in data

    file_id = uuid.UUID(data["file_object_id"])
    file_obj = db.query(FileObject).filter(FileObject.id == file_id).first()
    assert file_obj is not None

    # 2. Disk path verification: {upload_root}/{company_id}/{random_id}.pdf
    stored_path = file_obj.storage_path
    assert str(upload_root) in stored_path
    assert str(emp1.company_id) in stored_path
    assert raw_client_name not in stored_path
    assert stored_path.endswith(".pdf")
    assert os.path.exists(stored_path)


# ── F5: Signed link lifetime and download verification ────────────────────


def test_f5_signed_link_lifetime_10_minutes(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """F5: Signed link lasts 10 minutes (600s). Bad signature or expired gives 403.
    Missing record or missing file on disk gives 404.
    """
    hr1 = files_setup["hr1"]
    r_up = client.post(
        "/api/v1/files/upload",
        files={"file": ("valid.pdf", b"%PDF-1.4 file data", "application/pdf")},
        headers=_auth_headers(hr1),
    )
    assert r_up.status_code == 201
    file_id = r_up.json()["file_object_id"]

    # 1. Link issue: expires_in_seconds == 600
    r_url = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr1))
    assert r_url.status_code == 200
    url_data = r_url.json()
    assert url_data["expires_in_seconds"] == 600
    dl_url = url_data["url"]

    # 2. Valid download -> 200
    r_dl = client.get(dl_url)
    assert r_dl.status_code == 200
    assert r_dl.content == b"%PDF-1.4 file data"

    # 3. Bad signature -> 403
    bad_sig_url = dl_url.replace("signature=", "signature=bad_tampered_")
    r_bad_sig = client.get(bad_sig_url)
    assert r_bad_sig.status_code == 403
    assert r_bad_sig.json()["error"]["code"] == "forbidden"

    # 4. Expired signature -> 403
    past_ts = int((datetime.now(UTC) - timedelta(minutes=15)).timestamp())
    sig_payload = f"{hr1.company_id}:{file_id}:{past_ts}".encode()
    exp_sig = hmac.new(settings.SECRET_KEY.encode(), sig_payload, hashlib.sha256).hexdigest()
    exp_url = f"/api/v1/files/download/{file_id}?expires={past_ts}&signature={exp_sig}"
    r_exp = client.get(exp_url)
    assert r_exp.status_code == 403
    assert r_exp.json()["error"]["code"] == "forbidden"

    # 5. Missing record -> 404
    missing_id = uuid.uuid4()
    future_ts = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    missing_payload = f"{hr1.company_id}:{missing_id}:{future_ts}".encode()
    missing_sig = hmac.new(
        settings.SECRET_KEY.encode(), missing_payload, hashlib.sha256
    ).hexdigest()
    missing_url = f"/api/v1/files/download/{missing_id}?expires={future_ts}&signature={missing_sig}"
    r_missing = client.get(missing_url)
    assert r_missing.status_code == 404

    # 6. Missing file on disk -> 404
    file_obj = db.query(FileObject).filter(FileObject.id == uuid.UUID(file_id)).first()
    assert file_obj is not None
    if os.path.exists(file_obj.storage_path):
        os.remove(file_obj.storage_path)

    r_file_missing = client.get(dl_url)
    assert r_file_missing.status_code == 404


# ── F6: Cross company isolation ───────────────────────────────────────────


def test_f6_cross_company_isolation(client: TestClient, files_setup: dict[str, Any]) -> None:
    """F6: Another company never reaches a file (404 at issue time; signature binds company)."""
    hr1 = files_setup["hr1"]
    hr2 = files_setup["hr2"]
    c2 = files_setup["company2"]

    # Company 1 uploads file
    r_up = client.post(
        "/api/v1/files/upload",
        files={"file": ("tenant1.pdf", b"%PDF-1.4 t1 content", "application/pdf")},
        headers=_auth_headers(hr1),
    )
    assert r_up.status_code == 201
    file_id = r_up.json()["file_object_id"]

    # 1. Company 2 HR admin requesting link gives 404
    r_c2_url = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr2))
    assert r_c2_url.status_code == 404

    # 2. Company 2 constructing a signature with Company 2's company_id fails on download (403)
    future_ts = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    spoofed_payload = f"{c2.id}:{file_id}:{future_ts}".encode()
    spoofed_sig = hmac.new(
        settings.SECRET_KEY.encode(), spoofed_payload, hashlib.sha256
    ).hexdigest()
    spoofed_url = f"/api/v1/files/download/{file_id}?expires={future_ts}&signature={spoofed_sig}"
    r_spoofed = client.get(spoofed_url)
    assert r_spoofed.status_code == 403


# ── F7: Download headers, attachment, and path traversal ───────────────────


def test_f7_download_headers_and_attachment(
    client: TestClient, files_setup: dict[str, Any]
) -> None:
    """F7: Download is sent as an attachment, with the stored safe content type,
    X-Content-Type-Options: nosniff and Cache-Control: private, no-store.
    """
    hr1 = files_setup["hr1"]
    r_up = client.post(
        "/api/v1/files/upload",
        files={"file": ("photo_doc.png", _make_sample_png(), "image/png")},
        headers=_auth_headers(hr1),
    )
    assert r_up.status_code == 201
    file_id = r_up.json()["file_object_id"]

    r_url = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr1))
    assert r_url.status_code == 200
    dl_url = r_url.json()["url"]

    r_dl = client.get(dl_url)
    assert r_dl.status_code == 200
    assert r_dl.headers.get("x-content-type-options") == "nosniff"
    assert r_dl.headers.get("cache-control") == "private, no-store"
    assert "attachment" in r_dl.headers.get("content-disposition", "")
    assert "photo_doc.png" in r_dl.headers.get("content-disposition", "")
    assert "image/png" in r_dl.headers.get("content-type", "")


def test_f7_download_path_traversal_refusal(
    client: TestClient, files_setup: dict[str, Any], db: Session, tmp_path
) -> None:
    """F7, D4: File whose resolved path is outside the upload root gives 404."""
    hr1 = files_setup["hr1"]

    # Create file outside upload_root
    outside_dir = tmp_path / "outside_secret"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "external.pdf"
    outside_file.write_bytes(b"%PDF-1.4 external data")

    bind_tenant_to_session(db, company_id=hr1.company_id, is_platform_admin=True)
    file_obj = FileObject(
        id=uuid.uuid4(),
        company_id=hr1.company_id,
        uploaded_by=hr1.id,
        file_name="external.pdf",
        file_type="application/pdf",
        file_size=len(b"%PDF-1.4 external data"),
        storage_path=str(outside_file),
    )
    db.add(file_obj)
    db.commit()

    future_ts = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    sig_payload = f"{hr1.company_id}:{file_obj.id}:{future_ts}".encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), sig_payload, hashlib.sha256).hexdigest()
    dl_url = f"/api/v1/files/download/{file_obj.id}?expires={future_ts}&signature={sig}"

    r = client.get(dl_url)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ── F8: Audit logging and rate limits ─────────────────────────────────────


def test_f8_audit_rows_recorded(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """F8: Audit rows FILE_UPLOADED (file id, size, type) and FILE_LINK_ISSUED (file id)
    in the same commit; no file names in audit details.
    """
    emp1 = files_setup["emp1_user"]
    emp_headers = _auth_headers(emp1)

    r_up = client.post(
        "/api/v1/files/upload",
        files={"file": ("audit_check.pdf", b"%PDF-1.4 audit content", "application/pdf")},
        headers=emp_headers,
    )
    assert r_up.status_code == 201
    file_id = r_up.json()["file_object_id"]

    # Verify FILE_UPLOADED audit log
    up_audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == emp1.company_id,
            AuditLog.action == "FILE_UPLOADED",
            AuditLog.entity_id == uuid.UUID(file_id),
        )
        .first()
    )
    assert up_audit is not None
    assert up_audit.details.get("file_id") == file_id
    assert up_audit.details.get("file_size") == len(b"%PDF-1.4 audit content")
    assert up_audit.details.get("file_type") == "application/pdf"
    assert "file_name" not in up_audit.details
    assert "storage_path" not in up_audit.details

    # Issue link
    r_url = client.get(f"/api/v1/files/{file_id}/url", headers=emp_headers)
    assert r_url.status_code == 200

    # Verify FILE_LINK_ISSUED audit log
    link_audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == emp1.company_id,
            AuditLog.action == "FILE_LINK_ISSUED",
            AuditLog.entity_id == uuid.UUID(file_id),
        )
        .first()
    )
    assert link_audit is not None
    assert link_audit.details.get("file_id") == file_id
    assert "file_name" not in link_audit.details


def test_f8_upload_rate_limit_20_per_min(client: TestClient, files_setup: dict[str, Any]) -> None:
    """F8: POST /api/v1/files/upload rate limited at 20/min. 21st call returns 429."""
    emp1 = files_setup["emp1_user"]
    emp_headers = _auth_headers(emp1)

    limiter.enabled = True
    try:
        limiter.reset()
        statuses = []
        for i in range(21):
            r = client.post(
                "/api/v1/files/upload",
                files={"file": (f"f{i}.pdf", b"%PDF-1.4 sample", "application/pdf")},
                headers=emp_headers,
            )
            statuses.append(r.status_code)
        assert all(s == 201 for s in statuses[:20])
        assert statuses[20] == 429
    finally:
        limiter.reset()
        limiter.enabled = False


def test_f8_link_rate_limit_60_per_min(client: TestClient, files_setup: dict[str, Any]) -> None:
    """F8: GET /api/v1/files/{file_id}/url rate limited at 60/min. 61st call returns 429."""
    hr1 = files_setup["hr1"]
    r_up = client.post(
        "/api/v1/files/upload",
        files={"file": ("rate.pdf", b"%PDF-1.4 rate check", "application/pdf")},
        headers=_auth_headers(hr1),
    )
    assert r_up.status_code == 201
    file_id = r_up.json()["file_object_id"]

    limiter.enabled = True
    try:
        limiter.reset()
        statuses = []
        for _ in range(61):
            r = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr1))
            statuses.append(r.status_code)
        assert all(s == 200 for s in statuses[:60])
        assert statuses[60] == 429
    finally:
        limiter.reset()
        limiter.enabled = False


def test_f8_download_rate_limit_60_per_min(client: TestClient, files_setup: dict[str, Any]) -> None:
    """F8: GET /api/v1/files/download/{file_id} rate limited at 60/min. 61st call returns 429."""
    hr1 = files_setup["hr1"]
    r_up = client.post(
        "/api/v1/files/upload",
        files={"file": ("dl_rate.pdf", b"%PDF-1.4 dl rate", "application/pdf")},
        headers=_auth_headers(hr1),
    )
    assert r_up.status_code == 201
    file_id = r_up.json()["file_object_id"]

    r_url = client.get(f"/api/v1/files/{file_id}/url", headers=_auth_headers(hr1))
    assert r_url.status_code == 200
    dl_url = r_url.json()["url"]

    limiter.enabled = True
    try:
        limiter.reset()
        statuses = []
        for _ in range(61):
            r = client.get(dl_url)
            statuses.append(r.status_code)
        assert all(s == 200 for s in statuses[:60])
        assert statuses[60] == 429
    finally:
        limiter.reset()
        limiter.enabled = False


# ── Fix 1 tests ──────────────────────────────────────────────────────────


def test_f3_project_upload_over_limit_413(
    client: TestClient, files_setup: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project document upload over 25 MB returns 413 and stores nothing."""
    monkeypatch.setattr("app.modules.platform.service.MAX_FILE_UPLOAD_BYTES", 100 * 1024 * 1024)
    c1 = files_setup["company1"]
    hr1 = files_setup["hr1"]
    bind_tenant_to_session(db, company_id=c1.id, is_platform_admin=True)
    project = Project(
        id=uuid.uuid4(),
        company_id=c1.id,
        name="Project Over Limit",
        code=f"POL-{uuid.uuid4().hex[:4].upper()}",
        status="active",
    )
    db.add(project)
    db.commit()

    oversized = b"%PDF-1.4 " + (b"A" * (25 * 1024 * 1024))
    res = client.post(
        f"/api/v1/projects/{project.id}/documents",
        files={"file": ("huge.pdf", oversized, "application/pdf")},
        data={"description": "Oversized doc"},
        headers=_auth_headers(hr1),
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "file_too_large"
    docs = db.query(ProjectDocument).filter(ProjectDocument.project_id == project.id).all()
    assert len(docs) == 0


def test_f3_project_upload_not_allowed_type_422(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """Project document upload with disallowed type returns 422."""
    c1 = files_setup["company1"]
    hr1 = files_setup["hr1"]
    bind_tenant_to_session(db, company_id=c1.id, is_platform_admin=True)
    project = Project(
        id=uuid.uuid4(),
        company_id=c1.id,
        name="Project Invalid Type",
        code=f"PIT-{uuid.uuid4().hex[:4].upper()}",
        status="active",
    )
    db.add(project)
    db.commit()

    res = client.post(
        f"/api/v1/projects/{project.id}/documents",
        files={"file": ("bad.exe", b"MZ fake executable binary", "application/x-msdownload")},
        data={"description": "Invalid doc"},
        headers=_auth_headers(hr1),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_f8_project_upload_audit_has_actor(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """Project document upload records FILE_UPLOADED audit log with actor_id = uploader."""
    c1 = files_setup["company1"]
    hr1 = files_setup["hr1"]
    bind_tenant_to_session(db, company_id=c1.id, is_platform_admin=True)
    project = Project(
        id=uuid.uuid4(),
        company_id=c1.id,
        name="Project Audit Actor",
        code=f"PAA-{uuid.uuid4().hex[:4].upper()}",
        status="active",
    )
    db.add(project)
    db.commit()

    res = client.post(
        f"/api/v1/projects/{project.id}/documents",
        files={"file": ("project_spec.pdf", b"%PDF-1.4 spec bytes", "application/pdf")},
        data={"description": "Valid spec"},
        headers=_auth_headers(hr1),
    )
    assert res.status_code == 201
    file_id = res.json()["file_id"]

    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == c1.id,
            AuditLog.action == "FILE_UPLOADED",
            AuditLog.entity_id == uuid.UUID(file_id),
        )
        .first()
    )
    assert audit is not None
    assert audit.actor_user_id == hr1.id


def test_f8_project_document_list_writes_no_audit_rows(
    client: TestClient, files_setup: dict[str, Any], db: Session
) -> None:
    """Listing project documents must write NO FILE_LINK_ISSUED audit rows."""
    c1 = files_setup["company1"]
    hr1 = files_setup["hr1"]
    bind_tenant_to_session(db, company_id=c1.id, is_platform_admin=True)
    project = Project(
        id=uuid.uuid4(),
        company_id=c1.id,
        name="Project List Audits",
        code=f"PLA-{uuid.uuid4().hex[:4].upper()}",
        status="active",
    )
    db.add(project)
    db.commit()

    res_up = client.post(
        f"/api/v1/projects/{project.id}/documents",
        files={"file": ("test_doc.pdf", b"%PDF-1.4 doc bytes", "application/pdf")},
        data={"description": "A doc"},
        headers=_auth_headers(hr1),
    )
    assert res_up.status_code == 201

    initial_count = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == c1.id,
            AuditLog.action == "FILE_LINK_ISSUED",
        )
        .count()
    )

    r1 = client.get(f"/api/v1/projects/{project.id}/documents", headers=_auth_headers(hr1))
    assert r1.status_code == 200
    r2 = client.get(f"/api/v1/projects/{project.id}/documents", headers=_auth_headers(hr1))
    assert r2.status_code == 200

    after_count = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == c1.id,
            AuditLog.action == "FILE_LINK_ISSUED",
        )
        .count()
    )
    assert after_count == initial_count


def test_f1_signed_link_requires_user(files_setup: dict[str, Any]) -> None:
    """FileService.generate_signed_url requires user: User (no default)."""
    from app.modules.platform.service import FileService

    sig = inspect.signature(FileService.generate_signed_url)
    assert "user" in sig.parameters
    user_param = sig.parameters["user"]
    assert user_param.default is inspect.Parameter.empty, (
        "generate_signed_url user param must have no default"
    )
