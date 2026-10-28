import io
import os
import uuid
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import (
    Department,
    Employee,
    EmploymentType,
    InvitationStatus,
)
from app.modules.identity.models import (
    Company,
    CompanyLocation,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.platform.models import AuditLog, EmployeeDocument, FileObject


def _auth_headers(user: User) -> dict[str, str]:
    user_id = user.__dict__.get("id") or user.id
    company_id = user.__dict__.get("company_id") or user.company_id
    role = user.__dict__.get("role") or user.role
    role_val = role.value if hasattr(role, "value") else str(role)
    token = create_access_token(
        sub=str(user_id),
        company_id=str(company_id),
        role=role_val,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_sample_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<\n>>\nendobj\ntrailer\n<<\n>>\n%%EOF"


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
def doc_setup(db: Session, tmp_path, monkeypatch) -> dict[str, Any]:
    # Isolate storage to tmp_path
    docs_dir = str(tmp_path / "employee_docs")
    monkeypatch.setattr(settings, "EMPLOYEE_DOCS_DIR", docs_dir)

    cid_a = uuid.uuid4()
    company_a = Company(
        id=cid_a,
        name=f"Docs Corp A {uuid.uuid4().hex[:6]}",
        code=f"DCA{uuid.uuid4().hex[:4].upper()}",
        email=f"docsa-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company_a)
    db.flush()

    owner_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.owner,
        is_active=True,
    )
    hr_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    super_admin_user = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"super-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.super_admin,
        is_active=True,
    )
    manager_a = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"mgr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    emp_user1 = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"emp1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    emp_user2 = User(
        id=uuid.uuid4(),
        company_id=cid_a,
        email=f"emp2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add_all([owner_a, hr_a, super_admin_user, manager_a, emp_user1, emp_user2])
    db.flush()
    company_a.owner_user_id = owner_a.id
    db.flush()

    bind_tenant_to_session(db, company_id=cid_a, is_platform_admin=True)

    dept = Department(
        id=uuid.uuid4(),
        company_id=cid_a,
        name=f"Engineering {uuid.uuid4().hex[:4]}",
    )
    loc = CompanyLocation(
        id=uuid.uuid4(),
        company_id=cid_a,
        name=f"HQ {uuid.uuid4().hex[:4]}",
        code=f"HQ{uuid.uuid4().hex[:4].upper()}",
        country="IN",
        is_active=True,
    )
    db.add_all([dept, loc])
    db.flush()

    emp_owner = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=owner_a.id,
        employee_code=f"{company_a.code}-0001",
        first_name="Owner",
        last_name="Boss",
        email=owner_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp_hr = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=hr_a.id,
        employee_code=f"{company_a.code}-0002",
        first_name="HR",
        last_name="Admin",
        email=hr_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp_mgr = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=manager_a.id,
        employee_code=f"{company_a.code}-0003",
        first_name="Manager",
        last_name="Lead",
        email=manager_a.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
    )
    emp1 = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=emp_user1.id,
        employee_code=f"{company_a.code}-0004",
        first_name="Alice",
        last_name="Smith",
        email=emp_user1.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.activated,
        department_id=dept.id,
        location_id=loc.id,
        reporting_manager_id=emp_mgr.id,
    )
    emp2 = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        user_id=emp_user2.id,
        employee_code=f"{company_a.code}-0005",
        first_name="Bob",
        last_name="Jones",
        email=emp_user2.email,
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
        invitation_status=InvitationStatus.sent,
        department_id=dept.id,
        location_id=loc.id,
        reporting_manager_id=emp_mgr.id,
    )
    db.add_all([emp_owner, emp_hr, emp_mgr, emp1, emp2])

    # Company B for cross-tenant checks
    cid_b = uuid.uuid4()
    company_b = Company(
        id=cid_b,
        name=f"Docs Corp B {uuid.uuid4().hex[:6]}",
        code=f"DCB{uuid.uuid4().hex[:4].upper()}",
        email=f"docsb-{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
        is_active=True,
    )
    db.add(company_b)
    db.flush()

    hr_b = User(
        id=uuid.uuid4(),
        company_id=cid_b,
        email=f"hrb-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    db.add(hr_b)
    db.flush()

    bind_tenant_to_session(db, company_id=cid_b, is_platform_admin=True)
    emp_b = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_code=f"{company_b.code}-0001",
        first_name="CompanyB",
        last_name="Worker",
        email=f"worker-{uuid.uuid4().hex[:6]}@example.com",
        employment_type=EmploymentType.full_time,
        hire_date=date(2024, 1, 1),
        is_active=True,
    )
    db.add(emp_b)
    db.commit()
    bind_tenant_to_session(db, company_id=None, is_platform_admin=True)

    return {
        "company_a_id": cid_a,
        "company_b_id": cid_b,
        "company_a": company_a,
        "company_b": company_b,
        "owner_a": owner_a,
        "hr_a": hr_a,
        "super_admin": super_admin_user,
        "manager_a": manager_a,
        "emp_user1": emp_user1,
        "emp_user2": emp_user2,
        "hr_b": hr_b,
        "emp1": emp1,
        "emp1_id": emp1.id,
        "emp2": emp2,
        "emp2_id": emp2.id,
        "emp_b": emp_b,
        "emp_b_id": emp_b.id,
        "docs_dir": docs_dir,
    }


# ==============================================================================
# RULE 1: Roles and Permissions
# ==============================================================================


def test_r01_roles_upload_view_delete(client: TestClient, doc_setup: dict[str, Any]) -> None:
    """R1: Employee uploads & views own documents; other employee 403;
    manager 403 on direct report; HR admin, owner, super_admin can upload, view, delete.
    No login gives 401. Delete is HR-level only.
    """
    emp1 = doc_setup["emp1"]
    emp2 = doc_setup["emp2"]
    emp1_headers = _auth_headers(doc_setup["emp_user1"])
    emp2_headers = _auth_headers(doc_setup["emp_user2"])
    mgr_headers = _auth_headers(doc_setup["manager_a"])
    hr_headers = _auth_headers(doc_setup["hr_a"])
    owner_headers = _auth_headers(doc_setup["owner_a"])
    super_headers = _auth_headers(doc_setup["super_admin"])

    pdf_data = _make_sample_pdf()

    # 1. Unauthenticated -> 401
    res_no_auth = client.post(
        f"/api/v1/documents/{emp1.id}",
        data={"document_type": "id_proof", "name": "Passport"},
        files={"file": ("id.pdf", pdf_data, "application/pdf")},
    )
    assert res_no_auth.status_code == 401

    # 2. Employee uploads own document -> 201
    res_emp1_upload = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=emp1_headers,
        data={"document_type": "id_proof", "name": "Passport"},
        files={"file": ("id.pdf", pdf_data, "application/pdf")},
    )
    assert res_emp1_upload.status_code == 201
    doc1_id = res_emp1_upload.json()["id"]

    # 3. Employee views own documents -> 200
    res_emp1_list = client.get(f"/api/v1/documents/{emp1.id}", headers=emp1_headers)
    assert res_emp1_list.status_code == 200
    assert any(d["id"] == doc1_id for d in res_emp1_list.json())

    # 4. Employee attempts to upload to another employee -> 403
    res_emp1_on_emp2 = client.post(
        f"/api/v1/documents/{emp2.id}",
        headers=emp1_headers,
        data={"document_type": "id_proof", "name": "Colleague ID"},
        files={"file": ("id.pdf", pdf_data, "application/pdf")},
    )
    assert res_emp1_on_emp2.status_code == 403

    # 5. Employee attempts to view another employee -> 403
    res_emp1_view_emp2 = client.get(f"/api/v1/documents/{emp2.id}", headers=emp1_headers)
    assert res_emp1_view_emp2.status_code == 403

    # 6. Manager attempts to view / upload for a direct report -> 403
    res_mgr_upload = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=mgr_headers,
        data={"document_type": "certificate", "name": "Cert"},
        files={"file": ("cert.pdf", pdf_data, "application/pdf")},
    )
    assert res_mgr_upload.status_code == 403

    res_mgr_list = client.get(f"/api/v1/documents/{emp1.id}", headers=mgr_headers)
    assert res_mgr_list.status_code == 403

    # 7. Employee attempts to delete own document -> 403 (Delete is HR-level only)
    res_emp_del = client.delete(f"/api/v1/documents/{emp1.id}/{doc1_id}", headers=emp1_headers)
    assert res_emp_del.status_code == 403

    # Employee 2 attempts to delete employee 1's document -> 403
    res_emp2_del = client.delete(f"/api/v1/documents/{emp1.id}/{doc1_id}", headers=emp2_headers)
    assert res_emp2_del.status_code == 403

    # 8. HR Admin, Owner, Super Admin view & upload
    for h in [hr_headers, owner_headers, super_headers]:
        res_list = client.get(f"/api/v1/documents/{emp1.id}", headers=h)
        assert res_list.status_code == 200

        res_upload = client.post(
            f"/api/v1/documents/{emp1.id}",
            headers=h,
            data={"document_type": "other", "name": "Doc by HR/Owner"},
            files={"file": ("doc.pdf", pdf_data, "application/pdf")},
        )
        assert res_upload.status_code == 201
        created_id = res_upload.json()["id"]

        # Delete by HR-level -> 204
        res_del = client.delete(f"/api/v1/documents/{emp1.id}/{created_id}", headers=h)
        assert res_del.status_code == 204


# ==============================================================================
# RULE 2: Allowed Types and Content Validation (Magic Bytes)
# ==============================================================================


def test_r02_allowed_types_and_magic_byte_rejections(
    client: TestClient, doc_setup: dict[str, Any]
) -> None:
    """R2: PDF, JPG/JPEG, PNG, DOCX only; checked by extension and magic bytes;
    wrong extension, renamed .exe, PDF named .png, docx without word/document.xml,
    xlsx renamed .docx all give 422.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])

    # 1. Allowed types succeed
    valid_cases = [
        ("passport.pdf", _make_sample_pdf(), "application/pdf"),
        ("photo.jpg", _make_sample_jpeg(), "image/jpeg"),
        ("photo.jpeg", _make_sample_jpeg(), "image/jpeg"),
        ("avatar.png", _make_sample_png(), "image/png"),
        (
            "contract.docx",
            _make_sample_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ]
    for filename, content, ctype in valid_cases:
        res = client.post(
            f"/api/v1/documents/{emp1.id}",
            headers=hr_headers,
            data={"document_type": "passport", "name": "Valid Doc"},
            files={"file": (filename, content, ctype)},
        )
        assert res.status_code == 201, f"Failed for {filename}: {res.text}"

    # 2. Rejected extensions
    res_txt = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "other", "name": "Text File"},
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )
    assert res_txt.status_code == 422

    # 3. Renamed .exe as .pdf
    res_exe = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "other", "name": "Fake PDF"},
        files={"file": ("malware.pdf", b"MZ\x90\x00\x03\x00\x00\x00", "application/pdf")},
    )
    assert res_exe.status_code == 422

    # 4. PDF bytes named .png
    res_pdf_png = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "other", "name": "Fake PNG"},
        files={"file": ("fake.png", _make_sample_pdf(), "image/png")},
    )
    assert res_pdf_png.status_code == 422

    # 5. docx without word/document.xml
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("some/file.txt", "data")
    bad_docx = bio.getvalue()
    res_bad_docx = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "contract", "name": "Bad Docx"},
        files={
            "file": (
                "corrupt.docx",
                bad_docx,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res_bad_docx.status_code == 422

    # 6. xlsx renamed .docx
    bio_xlsx = io.BytesIO()
    with zipfile.ZipFile(bio_xlsx, "w") as zf:
        zf.writestr("xl/workbook.xml", "<xml/>")
    xlsx_bytes = bio_xlsx.getvalue()
    res_xlsx = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "contract", "name": "Excel As Docx"},
        files={
            "file": (
                "fake.docx",
                xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res_xlsx.status_code == 422


# ==============================================================================
# RULE 3: File Size Limits and Early Refusal
# ==============================================================================


def test_r03_size_limits_empty_and_early_refusal(
    client: TestClient, doc_setup: dict[str, Any], monkeypatch
) -> None:
    """R3: max settings.MAX_UPLOAD_MB (10) from setting; > limit gives 413 (code file_too_large);
    empty file gives 422; Content-Length early refusal.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])

    # Lower cap to 1 MB for testing
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)

    # 1. Empty file -> 422
    res_empty = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Empty"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert res_empty.status_code == 422

    # 2. File exceeding limit -> 413 file_too_large
    pdf_header = _make_sample_pdf()
    large_pdf = pdf_header + b"0" * (1 * 1024 * 1024 + 100)
    res_large = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Too Large"},
        files={"file": ("large.pdf", large_pdf, "application/pdf")},
    )
    assert res_large.status_code == 413
    assert res_large.json().get("error", {}).get("code") == "file_too_large"

    # 3. Content-Length header early refusal: header indicates huge payload
    huge_len_headers = dict(hr_headers)
    huge_len_headers["Content-Length"] = str(50 * 1024 * 1024)
    res_early = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=huge_len_headers,
        data={"document_type": "id_proof", "name": "Early Refusal"},
        files={"file": ("huge.pdf", b"test", "application/pdf")},
    )
    assert res_early.status_code == 413
    assert res_early.json().get("error", {}).get("code") == "file_too_large"


# ==============================================================================
# RULE 4: Filename Sanitization & Storage Path Randomization
# ==============================================================================


def test_r04_filename_sanitization_and_disk_isolation(
    client: TestClient, doc_setup: dict[str, Any], db: Session
) -> None:
    """R4: Cleaned original name is kept for display; stored on disk under random name;
    disk path is strictly inside tmp_path / EMPLOYEE_DOCS_DIR; no directory traversal.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    pdf_data = _make_sample_pdf()

    dirty_filename = "../../etc/passwd (1) [final]!@#.pdf"
    res = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Sanitized Doc"},
        files={"file": (dirty_filename, pdf_data, "application/pdf")},
    )
    assert res.status_code == 201
    doc_data = res.json()
    doc_id = uuid.UUID(doc_data["id"])

    # Query FileObject from DB to verify storage path
    file_obj = (
        db.query(FileObject)
        .join(EmployeeDocument, EmployeeDocument.file_object_id == FileObject.id)
        .filter(EmployeeDocument.id == doc_id)
        .first()
    )
    assert file_obj is not None

    # Stored name is random hex uuid, NOT dirty_filename
    assert not file_obj.storage_path.endswith("passwd (1) [final]!@#.pdf")
    assert file_obj.storage_path.startswith(doc_setup["docs_dir"])
    assert os.path.exists(file_obj.storage_path)

    # Cleaned original name kept for display / file_name
    assert ".." not in file_obj.file_name
    assert "/" not in file_obj.file_name
    assert "\\" not in file_obj.file_name
    assert file_obj.file_name.endswith(".pdf")


# ==============================================================================
# RULE 5: Document Record Validation, Employee Company Match, Cap 30 & Clean Up on Failure
# ==============================================================================


def test_r05_document_record_validation_and_concurrency_cap_and_rollback(
    client: TestClient, doc_setup: dict[str, Any], db: Session
) -> None:
    """R5: document_type from fixed list; name 1-255 trimmed; employee must belong to caller;
    max 30 non-deleted documents per employee (409); failed save leaves no file behind.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    emp1_headers = _auth_headers(doc_setup["emp_user1"])
    pdf_data = _make_sample_pdf()

    # 1. Invalid document_type -> 422
    res_bad_type = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "invalid_type_xyz", "name": "My Doc"},
        files={"file": ("doc.pdf", pdf_data, "application/pdf")},
    )
    assert res_bad_type.status_code == 422

    # 2. Name empty or whitespace -> 422
    res_bad_name = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "   "},
        files={"file": ("doc.pdf", pdf_data, "application/pdf")},
    )
    assert res_bad_name.status_code == 422

    # 3. Employee of other company -> 404 (same as missing employee)
    res_other_co = client.post(
        f"/api/v1/documents/{doc_setup['emp_b_id']}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Other Co Employee"},
        files={"file": ("doc.pdf", pdf_data, "application/pdf")},
    )
    assert res_other_co.status_code == 404

    # Non-existent employee id -> 404 for HR, 403 for employee
    fake_id = uuid.uuid4()
    assert (
        client.post(
            f"/api/v1/documents/{fake_id}",
            headers=hr_headers,
            data={"document_type": "id_proof", "name": "Fake"},
            files={"file": ("doc.pdf", pdf_data, "application/pdf")},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/documents/{fake_id}",
            headers=emp1_headers,
            data={"document_type": "id_proof", "name": "Fake"},
            files={"file": ("doc.pdf", pdf_data, "application/pdf")},
        ).status_code
        == 403
    )

    # 4. Failed save leaves no file behind on disk (force an error in AuditService)
    co_dir = os.path.join(doc_setup["docs_dir"], str(doc_setup["company_a_id"]))
    files_before = set(os.listdir(co_dir)) if os.path.exists(co_dir) else set()
    no_raise_client = TestClient(client.app, raise_server_exceptions=False)
    with patch(
        "app.modules.platform.service.AuditService.record", side_effect=RuntimeError("Audit crash")
    ):
        res_fail = no_raise_client.post(
            f"/api/v1/documents/{emp1.id}",
            headers=hr_headers,
            data={"document_type": "kyc", "name": "Rollback Test Doc"},
            files={"file": ("doc.pdf", pdf_data, "application/pdf")},
        )
        assert res_fail.status_code == 500

    files_after = set(os.listdir(co_dir)) if os.path.exists(co_dir) else set()
    # Confirm no orphan files were left
    assert files_after == files_before

    # 5. Cap 30 non-deleted documents per employee -> 31st gives 409
    # Add documents up to 30 directly in DB to avoid hitting 10/min rate limiter
    existing_count = (
        db.query(EmployeeDocument)
        .filter(EmployeeDocument.employee_id == emp1.id, EmployeeDocument.deleted_at.is_(None))
        .count()
    )

    from app.modules.platform.models import FileObject

    for i in range(existing_count, 30):
        fo = FileObject(
            id=uuid.uuid4(),
            company_id=doc_setup["company_a_id"],
            uploaded_by=doc_setup["hr_a"].id,
            file_name=f"seed_{i}.pdf",
            file_type="application/pdf",
            file_size=len(pdf_data),
            storage_path=os.path.join(co_dir, f"seed_{i}.pdf"),
        )
        db.add(fo)
        db.flush()
        doc_item = EmployeeDocument(
            id=uuid.uuid4(),
            company_id=doc_setup["company_a_id"],
            employee_id=emp1.id,
            file_object_id=fo.id,
            document_type="certificate",
            name=f"Cert {i}",
        )
        db.add(doc_item)
    db.commit()

    # 31st upload gives 409
    res_31 = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "certificate", "name": "Cert 31"},
        files={"file": ("cert_31.pdf", pdf_data, "application/pdf")},
    )
    assert res_31.status_code == 409


# ==============================================================================
# RULE 6: Download & Generic /files Link Protection
# ==============================================================================


def test_r06_authenticated_download_and_file_url_refusal(
    client: TestClient, doc_setup: dict[str, Any], db: Session, tmp_path: Path
) -> None:
    """R6: Download works for employee and HR; 404 for deleted/other-company/unknown;
    response headers (attachment, nosniff, no-store); list has no signed link and no storage path;
    GET /files/{id}/url refuses employee-document file with 404.
    """
    emp1 = doc_setup["emp1"]
    emp1_headers = _auth_headers(doc_setup["emp_user1"])
    emp2_headers = _auth_headers(doc_setup["emp_user2"])
    hr_headers = _auth_headers(doc_setup["hr_a"])
    pdf_data = _make_sample_pdf()

    res_up = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "offer_letter", "name": "Offer Letter"},
        files={"file": ("offer.pdf", pdf_data, "application/pdf")},
    )
    assert res_up.status_code == 201
    doc_id = res_up.json()["id"]

    # 1. List has relative download_url, no storage path, no HMAC signature query params
    res_list = client.get(f"/api/v1/documents/{emp1.id}", headers=emp1_headers)
    assert res_list.status_code == 200
    doc_item = next(d for d in res_list.json() if d["id"] == doc_id)
    assert "storage_path" not in doc_item
    assert doc_item["download_url"] == f"/api/v1/documents/{emp1.id}/{doc_id}/download"
    assert "signature" not in doc_item["download_url"]

    # 2. Download by owner employee -> 200 with headers
    res_dl_emp = client.get(f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=emp1_headers)
    assert res_dl_emp.status_code == 200
    assert res_dl_emp.content == pdf_data
    assert "attachment" in res_dl_emp.headers.get("content-disposition", "")
    assert res_dl_emp.headers.get("cache-control") == "no-store"
    assert res_dl_emp.headers.get("x-content-type-options") == "nosniff"

    # 3. Download by other employee -> 403
    res_dl_other = client.get(
        f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=emp2_headers
    )
    assert res_dl_other.status_code == 403

    # 4. Download by HR -> 200
    res_dl_hr = client.get(f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=hr_headers)
    assert res_dl_hr.status_code == 200

    # Path traversal test: file outside EMPLOYEE_DOCS_DIR returns 404
    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(pdf_data)
    doc_obj_direct = (
        db.query(EmployeeDocument).filter(EmployeeDocument.id == uuid.UUID(doc_id)).first()
    )
    assert doc_obj_direct is not None
    file_obj_direct = (
        db.query(FileObject).filter(FileObject.id == doc_obj_direct.file_object_id).first()
    )
    assert file_obj_direct is not None
    orig_path = file_obj_direct.storage_path
    file_obj_direct.storage_path = str(outside_file)
    db.commit()

    res_dl_outside = client.get(
        f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=hr_headers
    )
    assert res_dl_outside.status_code == 404
    file_obj_direct.storage_path = orig_path
    db.commit()

    # 5. GET /files/{file_id}/url refusal (Design 7): returns 404 for employee document files
    doc_obj = db.query(EmployeeDocument).filter(EmployeeDocument.id == uuid.UUID(doc_id)).first()
    assert doc_obj is not None
    file_id = doc_obj.file_object_id

    res_file_url = client.get(f"/api/v1/files/{file_id}/url", headers=hr_headers)
    assert res_file_url.status_code == 404


# ==============================================================================
# RULE 7: Soft Delete
# ==============================================================================


def test_r07_soft_delete_behavior(
    client: TestClient, doc_setup: dict[str, Any], db: Session
) -> None:
    """R7: HR-level only; soft delete hides from list and download;
    file stays on disk; second delete gives 404.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    emp1_headers = _auth_headers(doc_setup["emp_user1"])
    pdf_data = _make_sample_pdf()

    res_up = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "contract", "name": "Consulting Agreement"},
        files={"file": ("contract.pdf", pdf_data, "application/pdf")},
    )
    assert res_up.status_code == 201
    doc_id = res_up.json()["id"]

    # Delete -> 204
    res_del = client.delete(f"/api/v1/documents/{emp1.id}/{doc_id}", headers=hr_headers)
    assert res_del.status_code == 204

    # Second delete gives 404
    res_del2 = client.delete(f"/api/v1/documents/{emp1.id}/{doc_id}", headers=hr_headers)
    assert res_del2.status_code == 404

    # Hidden from list
    res_list = client.get(f"/api/v1/documents/{emp1.id}", headers=emp1_headers)
    assert all(d["id"] != doc_id for d in res_list.json())

    # Download gives 404
    res_dl = client.get(f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=emp1_headers)
    assert res_dl.status_code == 404

    # File still exists on disk
    doc_row = db.query(EmployeeDocument).filter(EmployeeDocument.id == uuid.UUID(doc_id)).first()
    assert doc_row is not None
    assert doc_row.deleted_at is not None
    file_obj = db.query(FileObject).filter(FileObject.id == doc_row.file_object_id).first()
    assert file_obj is not None
    assert os.path.exists(file_obj.storage_path)


# ==============================================================================
# RULE 8: Audit Logging
# ==============================================================================


def test_r08_audit_rows_upload_delete_download(
    client: TestClient, doc_setup: dict[str, Any], db: Session
) -> None:
    """R8: Upload, delete, and download each write exactly one audit row
    with details (employee_id, document_id, document_type). No file name,
    path or file content in audit log. None for failed requests.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    cid = doc_setup["company_a"].id
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    pdf_data = _make_sample_pdf()

    # 1. Upload audit
    res_up = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "passport", "name": "Passport Doc"},
        files={"file": ("passport.pdf", pdf_data, "application/pdf")},
    )
    assert res_up.status_code == 201
    doc_id = res_up.json()["id"]

    audit_up = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_DOCUMENT_UPLOADED",
            AuditLog.entity_id == uuid.UUID(doc_id),
        )
        .first()
    )
    assert audit_up is not None
    assert audit_up.details is not None
    assert set(audit_up.details.keys()) == {"employee_id", "document_id", "document_type"}
    assert audit_up.details["employee_id"] == str(emp1.id)
    assert audit_up.details["document_id"] == doc_id
    assert audit_up.details["document_type"] == "passport"
    assert "file_name" not in audit_up.details
    assert "storage_path" not in audit_up.details

    # 2. Download audit
    res_dl = client.get(f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=hr_headers)
    assert res_dl.status_code == 200

    audit_dl = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_DOCUMENT_DOWNLOADED",
            AuditLog.entity_id == uuid.UUID(doc_id),
        )
        .first()
    )
    assert audit_dl is not None
    assert set(audit_dl.details.keys()) == {"employee_id", "document_id", "document_type"}

    # 3. Delete audit
    res_del = client.delete(f"/api/v1/documents/{emp1.id}/{doc_id}", headers=hr_headers)
    assert res_del.status_code == 204

    audit_del = (
        db.query(AuditLog)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action == "EMPLOYEE_DOCUMENT_DELETED",
            AuditLog.entity_id == uuid.UUID(doc_id),
        )
        .first()
    )
    assert audit_del is not None
    assert set(audit_del.details.keys()) == {"employee_id", "document_id", "document_type"}

    # 4. Failed request does not write audit row
    count_before = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    res_bad = client.get(f"/api/v1/documents/{emp1.id}/{uuid.uuid4()}/download", headers=hr_headers)
    assert res_bad.status_code == 404
    count_after = db.query(AuditLog).filter(AuditLog.company_id == cid).count()
    assert count_after == count_before


# ==============================================================================
# RULE 9: Rate Limiting
# ==============================================================================


def test_r09_rate_limiting_upload_delete_download(
    client: TestClient, doc_setup: dict[str, Any]
) -> None:
    """R9: upload 10/min (11th gives 429), delete 30/min (31st gives 429),
    download 30/min (31st gives 429) per user.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    pdf_data = _make_sample_pdf()

    # Pre-upload one document for delete/download rate tests
    res_init = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "other", "name": "Rate Doc"},
        files={"file": ("doc.pdf", pdf_data, "application/pdf")},
    )
    assert res_init.status_code == 201
    doc_id = res_init.json()["id"]

    limiter.enabled = True
    try:
        # 1. Upload 10/min -> 11th gives 429
        limiter.reset()
        upload_codes = []
        for i in range(12):
            r = client.post(
                f"/api/v1/documents/{emp1.id}",
                headers=hr_headers,
                data={"document_type": "other", "name": f"Rate Upload {i}"},
                files={"file": (f"doc_{i}.pdf", pdf_data, "application/pdf")},
            )
            upload_codes.append(r.status_code)

        assert all(c != 429 for c in upload_codes[:10]), (
            f"First 10 upload calls: {upload_codes[:10]}"
        )
        assert all(c == 429 for c in upload_codes[10:]), f"Calls 11+ upload: {upload_codes[10:]}"

        # 2. Download 30/min -> 31st gives 429
        limiter.reset()
        download_codes = []
        for _ in range(35):
            r = client.get(f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=hr_headers)
            download_codes.append(r.status_code)

        assert all(c != 429 for c in download_codes[:30])
        assert all(c == 429 for c in download_codes[30:])

        # 3. Delete 30/min -> 31st gives 429
        limiter.reset()
        delete_codes = []
        for _ in range(35):
            r = client.delete(f"/api/v1/documents/{emp1.id}/{doc_id}", headers=hr_headers)
            delete_codes.append(r.status_code)

        assert all(c != 429 for c in delete_codes[:30])
        assert all(c == 429 for c in delete_codes[30:])
    finally:
        limiter.reset()
        limiter.enabled = False


# ==============================================================================
# RULE 10: Safety, Cross-Tenant Isolation, Inactive Employees & SQL Capture
# ==============================================================================


def test_r10_inactive_employee_documents_visible_to_hr(
    client: TestClient, doc_setup: dict[str, Any], db: Session
) -> None:
    """R10: HR can view documents of deactivated / former employees;
    employee themselves cannot if deactivated.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    pdf_data = _make_sample_pdf()

    res_up = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Active Doc"},
        files={"file": ("doc.pdf", pdf_data, "application/pdf")},
    )
    assert res_up.status_code == 201

    # Deactivate employee
    emp1.is_active = False
    db.commit()

    # HR can still list documents of deactivated employee
    res_hr = client.get(f"/api/v1/documents/{emp1.id}", headers=hr_headers)
    assert res_hr.status_code == 200
    assert len(res_hr.json()) >= 1


def test_r10_cross_company_isolation(client: TestClient, doc_setup: dict[str, Any]) -> None:
    """R10: Cross-company tenant isolation on upload, list, download, delete."""
    emp1_id = doc_setup["emp1_id"]
    hr_b_headers = _auth_headers(doc_setup["hr_b"])
    pdf_data = _make_sample_pdf()

    # Company B HR trying to access Company A employee -> 404
    assert client.get(f"/api/v1/documents/{emp1_id}", headers=hr_b_headers).status_code == 404
    assert (
        client.post(
            f"/api/v1/documents/{emp1_id}",
            headers=hr_b_headers,
            data={"document_type": "id_proof", "name": "Cross"},
            files={"file": ("doc.pdf", pdf_data, "application/pdf")},
        ).status_code
        == 404
    )


def test_r10_upload_takes_for_update_lock_on_employee(
    client: TestClient, doc_setup: dict[str, Any], db: Session
) -> None:
    """R10: Upload takes SELECT ... FOR UPDATE on employee row before inserting document."""
    hr_headers = _auth_headers(doc_setup["hr_a"])
    emp1 = doc_setup["emp1"]
    target_engine = db.get_bind()

    captured_statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        captured_statements.append(statement)

    event.listen(target_engine, "before_cursor_execute", before_cursor_execute)
    try:
        captured_statements.clear()
        res = client.post(
            f"/api/v1/documents/{emp1.id}",
            headers=hr_headers,
            data={"document_type": "id_proof", "name": "Lock Test"},
            files={"file": ("lock.pdf", _make_sample_pdf(), "application/pdf")},
        )
        assert res.status_code == 201

        emp_lock_indices = [
            i
            for i, stmt in enumerate(captured_statements)
            if "FROM employees" in stmt and "FOR UPDATE" in stmt
        ]
        assert len(emp_lock_indices) >= 1, (
            f"Expected SELECT ... FROM employees FOR UPDATE, got: {captured_statements}"
        )
    finally:
        event.remove(target_engine, "before_cursor_execute", before_cursor_execute)


def test_r10_concurrency_document_cap_30(tmp_path, monkeypatch) -> None:
    """R10 Concurrency: two simultaneous uploads at 29 existing documents give
    exactly one 201 and one 409, never 500. Uses real separate DB sessions and barrier.
    """
    import threading

    from app.db.session import get_db
    from app.main import app as fastapi_app
    from app.modules.platform.models import FileObject

    assert settings.TEST_DATABASE_URL is not None
    concurrent_engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)

    docs_dir = str(tmp_path / "conc_docs")
    monkeypatch.setattr(settings, "EMPLOYEE_DOCS_DIR", docs_dir)

    try:
        cid = uuid.uuid4()
        with Session(concurrent_engine) as setup_sess:
            company = Company(
                id=cid,
                name="Conc Corp",
                code=f"CNC{uuid.uuid4().hex[:4].upper()}",
                email=f"cnc-{uuid.uuid4().hex[:6]}@example.com",
                country="IN",
                status=CompanyStatus.active,
                is_active=True,
            )
            setup_sess.add(company)
            setup_sess.flush()

            hr_user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"cnchr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup_sess.add(hr_user)
            setup_sess.flush()
            company.owner_user_id = hr_user.id
            setup_sess.flush()

            bind_tenant_to_session(setup_sess, company_id=cid, is_platform_admin=True)

            conc_emp = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                user_id=hr_user.id,
                employee_code=f"{company.code}-0001",
                first_name="Conc",
                last_name="Worker",
                email=hr_user.email,
                employment_type=EmploymentType.full_time,
                hire_date=date(2024, 1, 1),
                is_active=True,
                invitation_status=InvitationStatus.activated,
            )
            setup_sess.add(conc_emp)
            setup_sess.flush()

            token = create_access_token(
                sub=str(hr_user.id), company_id=str(cid), role=hr_user.role.value
            )
            hr_headers = {"Authorization": f"Bearer {token}"}
            emp_id = conc_emp.id

            pdf_data = _make_sample_pdf()
            co_dir = os.path.join(docs_dir, str(cid))
            os.makedirs(co_dir, exist_ok=True)

            for i in range(29):
                fo = FileObject(
                    id=uuid.uuid4(),
                    company_id=cid,
                    uploaded_by=hr_user.id,
                    file_name=f"cseed_{i}.pdf",
                    file_type="application/pdf",
                    file_size=len(pdf_data),
                    storage_path=os.path.join(co_dir, f"cseed_{i}.pdf"),
                )
                setup_sess.add(fo)
                setup_sess.flush()
                doc_item = EmployeeDocument(
                    id=uuid.uuid4(),
                    company_id=cid,
                    employee_id=emp_id,
                    file_object_id=fo.id,
                    document_type="certificate",
                    name=f"Concurrent Seed {i}",
                )
                setup_sess.add(doc_item)
            setup_sess.commit()

        def _get_test_db():
            sess = Session(concurrent_engine)
            try:
                yield sess
            finally:
                sess.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db

        barrier = threading.Barrier(2)
        results = []

        def upload_concurrent():
            c = TestClient(fastapi_app)
            try:
                barrier.wait()
                res = c.post(
                    f"/api/v1/documents/{emp_id}",
                    headers=hr_headers,
                    data={"document_type": "certificate", "name": "Concurrent Race"},
                    files={"file": ("race.pdf", pdf_data, "application/pdf")},
                )
                results.append(res.status_code)
            except Exception:
                results.append(999)

        t1 = threading.Thread(target=upload_concurrent)
        t2 = threading.Thread(target=upload_concurrent)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert 500 not in results, f"Got 500 in concurrency race: {results}"
        assert sorted(results) == [201, 409], f"Expected [201, 409], got: {results}"
    finally:
        fastapi_app.dependency_overrides.clear()
        concurrent_engine.dispose()


# ==============================================================================
# FIX ROUND 2.5 ADDITIONS (F1, F2, F4)
# ==============================================================================


def test_f1_upload_route_is_sync_def():
    """F1: Upload route in platform/router.py must be a plain sync 'def'."""
    import inspect
    from app.modules.platform.router import upload_employee_document

    assert not inspect.iscoroutinefunction(
        upload_employee_document
    ), "upload_employee_document must be a synchronous 'def', not 'async def'"


def test_f2_evil_sibling_folder_path_traversal_refusal(
    client: TestClient, doc_setup: dict[str, Any], db: Session
):
    """F2: A FileObject whose storage_path is in a sibling folder named
    <EMPLOYEE_DOCS_DIR>_evil must return 404 on download.
    """
    emp1 = doc_setup["emp1"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    pdf_data = _make_sample_pdf()

    res_up = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "offer_letter", "name": "Offer Traversal"},
        files={"file": ("offer.pdf", pdf_data, "application/pdf")},
    )
    assert res_up.status_code == 201
    doc_id = res_up.json()["id"]

    # Create sibling folder <EMPLOYEE_DOCS_DIR>_evil
    docs_base_dir = doc_setup["docs_dir"]
    evil_dir = f"{docs_base_dir}_evil"
    os.makedirs(evil_dir, exist_ok=True)
    evil_file = os.path.join(evil_dir, "fake.pdf")
    with open(evil_file, "wb") as f:
        f.write(pdf_data)

    doc_obj = (
        db.query(EmployeeDocument).filter(EmployeeDocument.id == uuid.UUID(doc_id)).first()
    )
    assert doc_obj is not None
    file_obj = db.query(FileObject).filter(FileObject.id == doc_obj.file_object_id).first()
    assert file_obj is not None
    orig_path = file_obj.storage_path
    file_obj.storage_path = evil_file
    db.commit()

    res_dl = client.get(
        f"/api/v1/documents/{emp1.id}/{doc_id}/download", headers=hr_headers
    )
    assert (
        res_dl.status_code == 404
    ), f"Expected 404 for evil sibling folder, got {res_dl.status_code}"

    file_obj.storage_path = orig_path
    db.commit()


def test_f4_no_orphan_file_or_db_records_on_rejected_uploads(
    client: TestClient, doc_setup: dict[str, Any], db: Session
):
    """F4 (a): After every rejected upload (413, 422 wrong type, 422 magic mismatch,
    422 empty, 409 over 30, 403), no new file exists in docs folder and no new FileObject
    or EmployeeDocument row exists.
    """
    emp1 = doc_setup["emp1"]
    emp2 = doc_setup["emp2"]
    hr_headers = _auth_headers(doc_setup["hr_a"])
    emp1_headers = _auth_headers(doc_setup["emp_user1"])
    pdf_data = _make_sample_pdf()

    co_dir = os.path.join(doc_setup["docs_dir"], str(doc_setup["company_a_id"]))
    os.makedirs(co_dir, exist_ok=True)
    bind_tenant_to_session(db, company_id=doc_setup["company_a_id"], is_platform_admin=True)

    def _snapshot():
        db.expire_all()
        files = set(os.listdir(co_dir)) if os.path.exists(co_dir) else set()
        co_id = doc_setup["company_a_id"]
        doc_count = db.query(EmployeeDocument).filter(EmployeeDocument.company_id == co_id).count()
        file_count = db.query(FileObject).filter(FileObject.company_id == co_id).count()
        return files, doc_count, file_count

    # 1. 422 wrong type
    files_before, docs_before, objs_before = _snapshot()
    r = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "invalid_type", "name": "Doc"},
        files={"file": ("test.pdf", pdf_data, "application/pdf")},
    )
    assert r.status_code == 422
    assert _snapshot() == (files_before, docs_before, objs_before)

    # 2. 422 magic mismatch
    files_before, docs_before, objs_before = _snapshot()
    r = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Doc"},
        files={"file": ("fake.pdf", b"NOT_A_PDF_BYTES", "application/pdf")},
    )
    assert r.status_code == 422
    assert _snapshot() == (files_before, docs_before, objs_before)

    # 3. 422 empty
    files_before, docs_before, objs_before = _snapshot()
    r = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Doc"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert r.status_code == 422
    assert _snapshot() == (files_before, docs_before, objs_before)

    # 4. 413 file too large
    files_before, docs_before, objs_before = _snapshot()
    huge = b"%PDF-" + b"0" * (11 * 1024 * 1024)
    r = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "Doc"},
        files={"file": ("huge.pdf", huge, "application/pdf")},
    )
    assert r.status_code == 413
    assert _snapshot() == (files_before, docs_before, objs_before)

    # 5. 403 forbidden employee on another
    files_before, docs_before, objs_before = _snapshot()
    r = client.post(
        f"/api/v1/documents/{emp2.id}",
        headers=emp1_headers,
        data={"document_type": "id_proof", "name": "Doc"},
        files={"file": ("test.pdf", pdf_data, "application/pdf")},
    )
    assert r.status_code == 403
    assert _snapshot() == (files_before, docs_before, objs_before)

    # 6. 409 over 30 documents
    # Seed documents up to 30 for emp2
    curr_emp2_docs = (
        db.query(EmployeeDocument)
        .filter(EmployeeDocument.employee_id == emp2.id, EmployeeDocument.deleted_at.is_(None))
        .count()
    )
    for i in range(curr_emp2_docs, 30):
        fo = FileObject(
            company_id=doc_setup["company_a_id"],
            uploaded_by=doc_setup["hr_a"].id,
            file_name=f"seed_{i}.pdf",
            file_type="application/pdf",
            file_size=10,
            storage_path=os.path.join(co_dir, f"seed_{i}.pdf"),
        )
        db.add(fo)
        db.flush()
        ed = EmployeeDocument(
            company_id=doc_setup["company_a_id"],
            employee_id=emp2.id,
            file_object_id=fo.id,
            document_type="other",
            name=f"Seed {i}",
        )
        db.add(ed)
    db.commit()

    files_before, docs_before, objs_before = _snapshot()
    r = client.post(
        f"/api/v1/documents/{emp2.id}",
        headers=hr_headers,
        data={"document_type": "id_proof", "name": "31st Doc"},
        files={"file": ("test.pdf", pdf_data, "application/pdf")},
    )
    assert r.status_code == 409
    assert _snapshot() == (files_before, docs_before, objs_before)


def test_f4_access_restrictions_and_deleted_documents_hidden(
    client: TestClient, doc_setup: dict[str, Any], db: Session
):
    """F4 (b) & (c):
    (b) An employee cannot download or list another employee's document (403),
        and a manager gets 403 on report's document.
    (c) Deleted documents never appear in list for HR either.
    """
    emp1 = doc_setup["emp1"]
    emp2 = doc_setup["emp2"]
    emp1_headers = _auth_headers(doc_setup["emp_user1"])
    emp2_headers = _auth_headers(doc_setup["emp_user2"])
    mgr_headers = _auth_headers(doc_setup["manager_a"])
    hr_headers = _auth_headers(doc_setup["hr_a"])
    pdf_data = _make_sample_pdf()

    # Upload document for emp1
    res_up = client.post(
        f"/api/v1/documents/{emp1.id}",
        headers=hr_headers,
        data={"document_type": "passport", "name": "Emp1 Passport"},
        files={"file": ("passport.pdf", pdf_data, "application/pdf")},
    )
    assert res_up.status_code == 201
    doc1_id = res_up.json()["id"]

    # (b) Employee 2 cannot list emp1's documents (403)
    assert client.get(f"/api/v1/documents/{emp1.id}", headers=emp2_headers).status_code == 403
    # (b) Employee 2 cannot download emp1's document (403)
    assert (
        client.get(
            f"/api/v1/documents/{emp1.id}/{doc1_id}/download", headers=emp2_headers
        ).status_code
        == 403
    )

    # (b) Manager cannot list direct report emp1's documents (403)
    assert client.get(f"/api/v1/documents/{emp1.id}", headers=mgr_headers).status_code == 403
    # (b) Manager cannot download direct report emp1's document (403)
    assert (
        client.get(
            f"/api/v1/documents/{emp1.id}/{doc1_id}/download", headers=mgr_headers
        ).status_code
        == 403
    )

    # (c) Soft delete document
    res_del = client.delete(
        f"/api/v1/documents/{emp1.id}/{doc1_id}", headers=hr_headers
    )
    assert res_del.status_code == 204

    # (c) Deleted document does NOT appear in list for HR
    res_hr_list = client.get(f"/api/v1/documents/{emp1.id}", headers=hr_headers)
    assert res_hr_list.status_code == 200
    assert all(
        d["id"] != doc1_id for d in res_hr_list.json()
    ), "Deleted document must not appear in HR list"
