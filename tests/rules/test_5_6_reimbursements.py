"""Module 5, sub-feature 5.6: Reimbursements. One test per rule line (R1..R10).

Dates are computed from utcnow() because the claim rules compare the expense date with today.
Receipts are `file_objects` rows written directly (who uploaded them and their content type
are what the rules look at); one test also goes through the real upload route.
The organisation used by most tests:

    boss (manager) -> mgr (manager) -> emp (employee), peer (employee)
    other_mgr (manager, outside the chain), hr (hr_admin without a profile), owner, hr2
"""

import io
import itertools
import threading
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core.time import utcnow
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import (
    Company,
    CompanySettings,
    CompanyStatus,
    User,
    UserRole,
)
from app.modules.payroll.models import Reimbursement, ReimbursementStatus, ReimbursementType
from app.modules.payroll.repository import ReimbursementRepository
from app.modules.payroll.service import ReimbursementService
from app.modules.platform.models import AuditLog, FileObject, Notification
from app.modules.platform.service import AuditService
from tests.conftest import REPO_ROOT, TenantContext
from tests.rules.test_5_4_payroll_runs import (
    RUNS,
    _extra_user,
    _filled_world,
    _item_for,
    _make_run,
    _seed_statutory,
    _set_flags,
    _staff,
    world,
)

# Fixtures borrowed from the 5.4 tests (pytest finds them by name in this module).
_BORROWED_FIXTURES = (world, _seed_statutory)

BASE = "/api/v1/payroll/reimbursements"
MIGRATION_REVISION = "11355755ef14"
PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_numbers = itertools.count(1)


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


# ---------------------------------------------------------------- helpers


def _day(back: int):
    return utcnow().date() - timedelta(days=back)


def _receipt(db: Session, ctx: TenantContext, user: User, file_type: str = PDF) -> str:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    file_object = FileObject(
        company_id=ctx.company_id,
        file_name="private-receipt-name.pdf",
        file_type=file_type,
        file_size=100,
        storage_path=f"/nowhere/{uuid.uuid4().hex}.pdf",
        uploaded_by=user.id,
    )
    db.add(file_object)
    db.commit()
    return str(file_object.id)


def _body(db: Session, org: dict[str, Any], who: str = "emp", **over: Any) -> dict[str, Any]:
    n = next(_numbers)
    body: dict[str, Any] = {
        "type": "travel",
        "amount": f"{100 + n}.00",
        "expense_date": _day(3).isoformat(),
        "description": "Cab to the client site",
        "file_object_id": _receipt(db, org["ctx"], org[who]["user"]),
    }
    body.update(over)
    return body


def _submit(client: TestClient, db: Session, org: dict[str, Any], who: str = "emp", **over: Any):
    return client.post(BASE, json=_body(db, org, who, **over), headers=org[who]["h"])


def _claim(client: TestClient, db: Session, org: dict[str, Any], who: str = "emp", **over: Any):
    resp = _submit(client, db, org, who, **over)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _decide(
    client: TestClient, headers: dict[str, str], claim_id: str, action: str = "approve", **x
):
    body: dict[str, Any] = {"action": action}
    body.update(x)
    return client.put(f"{BASE}/{claim_id}", json=body, headers=headers)


def _withdraw(client: TestClient, headers: dict[str, str], claim_id: str):
    return client.post(f"{BASE}/{claim_id}/withdraw", headers=headers)


def _list(client: TestClient, headers: dict[str, str], query: str = ""):
    return client.get(f"{BASE}{query}", headers=headers)


def _ids(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [c["id"] for c in resp.json()["items"]]


def _message(resp) -> str:
    """The error text, or the raw body when the response is not an error envelope."""
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    return error["message"] if isinstance(error, dict) else resp.text


def _fields(resp) -> set[str]:
    body = resp.json() if resp.content else {}
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    errors = details.get("errors", []) if isinstance(details, dict) else []
    return {str(e["loc"][-1]) for e in errors}


def _state(db: Session, ctx: TenantContext, claim_id: str) -> Reimbursement:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    db.expire_all()
    row = db.get(Reimbursement, uuid.UUID(claim_id))
    assert row is not None
    return row


def _force(db: Session, ctx: TenantContext, claim_id: str, **fields: Any) -> None:
    row = _state(db, ctx, claim_id)
    for key, value in fields.items():
        setattr(row, key, value)
    db.commit()


def _audit(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


def _notes(db: Session, ctx: TenantContext, user: User, kind: str | None = None):
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    query = db.query(Notification).filter(
        Notification.company_id == ctx.company_id, Notification.user_id == user.id
    )
    if kind is not None:
        query = query.filter(Notification.type == kind)
    return query.all()


@pytest.fixture
def org(client: TestClient, db: Session, company_a: TenantContext) -> dict[str, Any]:
    ctx = company_a
    boss = _staff(client, db, ctx, None, UserRole.manager)
    mgr = _staff(client, db, ctx, None, UserRole.manager)
    emp = _staff(client, db, ctx, None)
    peer = _staff(client, db, ctx, None)
    other_mgr = _staff(client, db, ctx, None, UserRole.manager)
    hr_emp = _staff(client, db, ctx, None, UserRole.hr_admin)
    owner_emp = _staff(client, db, ctx, None, UserRole.owner)
    _set_flags(db, ctx, mgr["id"], reporting_manager_id=uuid.UUID(boss["id"]))
    _set_flags(db, ctx, emp["id"], reporting_manager_id=uuid.UUID(mgr["id"]))
    _set_flags(db, ctx, peer["id"], reporting_manager_id=uuid.UUID(mgr["id"]))
    hr2_h, hr2_user = _extra_user(db, ctx.company_id, UserRole.hr_admin)
    owner_h, owner_user = _extra_user(db, ctx.company_id, UserRole.owner)
    return {
        "ctx": ctx,
        "boss": boss,
        "mgr": mgr,
        "emp": emp,
        "peer": peer,
        "other_mgr": other_mgr,
        "hr_emp": hr_emp,
        "owner_emp": owner_emp,
        "hr": ctx.hr_headers,
        "hr2": hr2_h,
        "owner": owner_h,
        "owner_user": owner_user,
    }


def _foreign_claim(client: TestClient, db: Session, other: TenantContext) -> dict[str, Any]:
    """A pending claim that belongs to another company."""
    staff = _staff(client, db, other, None)
    resp = client.post(
        BASE,
        json={
            "type": "food",
            "amount": "250.00",
            "expense_date": _day(2).isoformat(),
            "description": "Team lunch",
            "file_object_id": _receipt(db, other, staff["user"]),
        },
        headers=staff["h"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ------------------------------------------------------------------- R1


def test_R1_no_login_gets_401(client: TestClient) -> None:
    cid = uuid.uuid4()
    codes = [
        client.post(BASE, json={}).status_code,
        client.get(BASE).status_code,
        client.put(f"{BASE}/{cid}", json={"action": "approve"}).status_code,
        client.post(f"{BASE}/{cid}/withdraw").status_code,
    ]
    assert codes == [401] * 4, f"R1: no login must give 401 on every reimbursement route: {codes}"


def test_R1_an_employee_submits_a_claim_for_themselves(client, db, org) -> None:
    resp = _submit(client, db, org)
    assert resp.status_code == 201, resp.text
    claim = resp.json()
    assert claim["employee_id"] == org["emp"]["id"], "R1: the claim belongs to the claimant"
    assert claim["status"] == "pending", "R1: a new claim is pending"


@pytest.mark.parametrize("who", ["mgr", "hr_emp", "owner_emp"])
def test_R1_managers_hr_and_owner_with_a_profile_also_submit_for_themselves(
    client, db, org, who
) -> None:
    claim = _claim(client, db, org, who)
    assert claim["employee_id"] == org[who]["id"], f"R1: {who} claim must be their own"


def test_R1_a_user_without_an_employee_profile_cannot_submit(client, db, org) -> None:
    body = _body(db, org)
    resp = client.post(BASE, json=body, headers=org["ctx"].employee_headers)
    assert resp.status_code == 404, f"R1: no profile must give 404: {resp.text}"
    assert "Employee profile not found" in _message(resp), f"R1: message: {_message(resp)}"


def test_R1_a_receipt_is_required(client, db, org) -> None:
    body = _body(db, org)
    del body["file_object_id"]
    missing = client.post(BASE, json=body, headers=org["emp"]["h"])
    assert missing.status_code == 422, f"R1: a missing receipt must give 422: {missing.text}"
    assert "file_object_id" in _fields(missing), "R1: the error must name file_object_id"
    body["file_object_id"] = None
    null = client.post(BASE, json=body, headers=org["emp"]["h"])
    assert null.status_code == 422, f"R1: a null receipt must give 422: {null.text}"
    assert "file_object_id" in _fields(null), "R1: the error must name file_object_id"


def test_R1_someone_elses_another_companys_and_a_missing_receipt_give_the_same_404(
    client, db, org, company_b
) -> None:
    foreign_user = _staff(client, db, company_b, None)["user"]
    cases = {
        "someone else's file": _receipt(db, org["ctx"], org["peer"]["user"]),
        "another company's file": _receipt(db, company_b, foreign_user),
        "a missing file": str(uuid.uuid4()),
    }
    messages = set()
    for label, file_id in cases.items():
        resp = client.post(
            BASE, json=_body(db, org, file_object_id=file_id), headers=org["emp"]["h"]
        )
        assert resp.status_code == 404, f"R1: {label} must give 404: {resp.text}"
        messages.add(_message(resp))
    assert messages == {"Receipt file not found."}, f"R1: one message for all three: {messages}"


def test_R1_a_file_uploaded_by_hr_cannot_be_used_by_the_employee(client, db, org) -> None:
    hr_user = org["hr_emp"]["user"]
    file_id = _receipt(db, org["ctx"], hr_user)
    resp = client.post(BASE, json=_body(db, org, file_object_id=file_id), headers=org["emp"]["h"])
    assert resp.status_code == 404, f"R1: only the claimant's own upload counts: {resp.text}"


@pytest.mark.parametrize("file_type", [PDF, PNG, JPEG])
def test_R1_pdf_png_and_jpg_receipts_are_accepted(client, db, org, file_type) -> None:
    receipt = _receipt(db, org["ctx"], org["emp"]["user"], file_type)
    resp = _submit(client, db, org, file_object_id=receipt)
    assert resp.status_code == 201, f"R1: {file_type} must be accepted: {resp.text}"


@pytest.mark.parametrize("file_type", [DOCX, "text/plain", "application/zip", "image/gif"])
def test_R1_other_receipt_types_give_422(client, db, org, file_type) -> None:
    receipt = _receipt(db, org["ctx"], org["emp"]["user"], file_type)
    resp = _submit(client, db, org, file_object_id=receipt)
    assert resp.status_code == 422, f"R1: {file_type} must give 422: {resp.text}"
    assert _message(resp) == "The receipt must be a PDF, PNG or JPG file.", _message(resp)


def test_R1_a_receipt_from_the_real_upload_route_works(client, db, org) -> None:
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    up = client.post(
        "/api/v1/files/upload",
        files={"file": ("bill.pdf", io.BytesIO(pdf), "application/pdf")},
        headers=org["emp"]["h"],
    )
    assert up.status_code == 201, up.text
    resp = _submit(client, db, org, file_object_id=up.json()["file_object_id"])
    assert resp.status_code == 201, f"R1: an uploaded PDF must work as a receipt: {resp.text}"


# ------------------------------------------------------------------- R2


@pytest.mark.parametrize("kind", ["travel", "food", "medical", "telephone", "other"])
def test_R2_every_listed_type_is_accepted(client, db, org, kind) -> None:
    assert _claim(client, db, org, type=kind)["type"] == kind


@pytest.mark.parametrize("kind", ["fuel", "", "TRAVEL", None, 5])
def test_R2_an_unlisted_type_gives_422(client, db, org, kind) -> None:
    resp = _submit(client, db, org, type=kind)
    assert resp.status_code == 422, f"R2: type {kind!r} must give 422: {resp.text}"
    assert "type" in _fields(resp), "R2: the error must name the type field"


@pytest.mark.parametrize(
    "amount", ["0", "0.00", "-1.00", "1000000.01", "10.555", "abc", "", None, "1e7"]
)
def test_R2_a_bad_amount_gives_422(client, db, org, amount) -> None:
    resp = _submit(client, db, org, amount=amount)
    assert resp.status_code == 422, f"R2: amount {amount!r} must give 422: {resp.text}"
    assert "amount" in _fields(resp), "R2: the error must name the amount field"


@pytest.mark.parametrize("amount", ["0.01", "1500.50", "1000000.00", "7"])
def test_R2_amounts_up_to_the_limit_are_stored_exactly(client, db, org, amount) -> None:
    claim = _claim(client, db, org, amount=amount)
    assert Decimal(claim["amount"]) == Decimal(amount), f"R2: amount changed: {claim['amount']}"
    stored = _state(db, org["ctx"], claim["id"]).amount
    assert stored == Decimal(amount), "R2: the stored amount must be exact"


def test_R2_the_expense_date_cannot_be_in_the_future(client, db, org) -> None:
    resp = _submit(client, db, org, expense_date=_day(-1).isoformat())
    assert resp.status_code == 422, f"R2: tomorrow must give 422: {resp.text}"
    assert _message(resp) == "The expense date cannot be in the future.", _message(resp)
    assert _submit(client, db, org, expense_date=_day(0).isoformat()).status_code == 201, (
        "R2: today is allowed"
    )


def test_R2_the_expense_date_cannot_be_older_than_90_days(client, db, org) -> None:
    resp = _submit(client, db, org, expense_date=_day(91).isoformat())
    assert resp.status_code == 422, f"R2: 91 days ago must give 422: {resp.text}"
    assert _message(resp) == "The expense date cannot be older than 90 days.", _message(resp)
    assert _submit(client, db, org, expense_date=_day(90).isoformat()).status_code == 201, (
        "R2: exactly 90 days ago is allowed"
    )


@pytest.mark.parametrize("bad", ["not-a-date", "2025-13-40", "", None, 20250101])
def test_R2_a_bad_date_gives_422(client, db, org, bad) -> None:
    resp = _submit(client, db, org, expense_date=bad)
    assert resp.status_code == 422, f"R2: date {bad!r} must give 422: {resp.text}"


def test_R2_the_description_is_trimmed_and_must_be_1_to_500_characters(client, db, org) -> None:
    claim = _claim(client, db, org, description="  Taxi to airport  ")
    assert claim["description"] == "Taxi to airport", "R2: description must be trimmed"
    for bad in ("", "    ", "x" * 501, None):
        resp = _submit(client, db, org, description=bad)
        assert resp.status_code == 422, f"R2: description {str(bad)[:5]!r}.. must give 422"
        assert "description" in _fields(resp), "R2: the error must name description"
    assert _submit(client, db, org, description="x" * 500).status_code == 201, "R2: 500 is allowed"


@pytest.mark.parametrize(
    "extra",
    [
        {"employee_id": str(uuid.uuid4())},
        {"status": "approved"},
        {"added_to_payroll_run_id": str(uuid.uuid4())},
        {"approved_by": str(uuid.uuid4())},
        {"rejection_reason": "x"},
    ],
)
def test_R2_unknown_fields_give_422(client, db, org, extra) -> None:
    resp = _submit(client, db, org, **extra)
    assert resp.status_code == 422, f"R2: unknown field {list(extra)} must give 422: {resp.text}"


@pytest.mark.parametrize("field", ["type", "amount", "expense_date", "description"])
def test_R2_a_null_or_missing_required_field_gives_422(client, db, org, field) -> None:
    nulled = _submit(client, db, org, **{field: None})
    assert nulled.status_code == 422, f"R2: {field} null must give 422: {nulled.text}"
    body = _body(db, org)
    del body[field]
    missing = client.post(BASE, json=body, headers=org["emp"]["h"])
    assert missing.status_code == 422, f"R2: {field} missing must give 422: {missing.text}"
    assert field in _fields(missing), "R2: the error must name the missing field"


def test_R2_a_refused_claim_leaves_no_row(client, db, org) -> None:
    _submit(client, db, org, amount="0")
    _submit(client, db, org, description="")
    bind_tenant_to_session(db, company_id=org["ctx"].company_id, is_platform_admin=False)
    assert db.query(Reimbursement).count() == 0, "R2: a refused claim must save nothing"


# ------------------------------------------------------------------- R3


def test_R3_one_receipt_backs_one_open_claim(client, db, org) -> None:
    receipt = _receipt(db, org["ctx"], org["emp"]["user"])
    first = _claim(client, db, org, file_object_id=receipt)
    again = _submit(client, db, org, file_object_id=receipt)
    assert again.status_code == 409, (
        f"R3: a second claim on one receipt must give 409: {again.text}"
    )
    assert _message(again) == "This receipt is already attached to another claim.", _message(again)
    _decide(client, org["mgr"]["h"], first["id"])
    after_approval = _submit(client, db, org, file_object_id=receipt)
    assert after_approval.status_code == 409, "R3: an approved claim keeps its receipt"
    _force(db, org["ctx"], first["id"], status=ReimbursementStatus.paid)
    after_paid = _submit(client, db, org, file_object_id=receipt)
    assert after_paid.status_code == 409, "R3: a paid claim keeps its receipt"


def test_R3_a_rejected_claim_frees_its_receipt(client, db, org) -> None:
    receipt = _receipt(db, org["ctx"], org["emp"]["user"])
    first = _claim(client, db, org, file_object_id=receipt)
    _decide(client, org["mgr"]["h"], first["id"], "reject", rejection_reason="Not covered")
    again = _submit(client, db, org, file_object_id=receipt, amount="777.00")
    assert again.status_code == 201, f"R3: a rejected claim frees its receipt: {again.text}"


def test_R3_a_withdrawn_claim_frees_its_receipt(client, db, org) -> None:
    receipt = _receipt(db, org["ctx"], org["emp"]["user"])
    first = _claim(client, db, org, file_object_id=receipt)
    assert _withdraw(client, org["emp"]["h"], first["id"]).status_code == 200
    again = _submit(client, db, org, file_object_id=receipt, amount="778.00")
    assert again.status_code == 201, f"R3: a withdrawn claim frees its receipt: {again.text}"


def test_R3_the_same_employee_date_type_and_amount_as_an_open_claim_gives_409(
    client, db, org
) -> None:
    same = {"type": "food", "amount": "321.00", "expense_date": _day(4).isoformat()}
    first = _claim(client, db, org, **same)
    dup = _submit(client, db, org, **same)
    assert dup.status_code == 409, f"R3: a duplicate claim must give 409: {dup.text}"
    assert _message(dup) == "A claim for the same date, type and amount already exists.", _message(
        dup
    )
    _decide(client, org["mgr"]["h"], first["id"])
    assert _submit(client, db, org, **same).status_code == 409, "R3: duplicate of an approved one"
    _force(db, org["ctx"], first["id"], status=ReimbursementStatus.paid)
    assert _submit(client, db, org, **same).status_code == 409, "R3: duplicate of a paid one"


@pytest.mark.parametrize(
    "different",
    [{"amount": "322.00"}, {"expense_date": "OTHER_DAY"}, {"type": "medical"}],
)
def test_R3_a_claim_that_differs_in_amount_date_or_type_is_allowed(
    client, db, org, different
) -> None:
    same = {"type": "food", "amount": "321.00", "expense_date": _day(4).isoformat()}
    _claim(client, db, org, **same)
    changed = {k: (_day(5).isoformat() if v == "OTHER_DAY" else v) for k, v in different.items()}
    assert _submit(client, db, org, **{**same, **changed}).status_code == 201, (
        f"R3: {list(different)} differs, so it is not a duplicate"
    )


def test_R3_another_employee_with_the_same_data_is_not_a_duplicate(client, db, org) -> None:
    same = {"type": "food", "amount": "321.00", "expense_date": _day(4).isoformat()}
    _claim(client, db, org, "emp", **same)
    assert _submit(client, db, org, "peer", **same).status_code == 201, (
        "R3: the duplicate rule is per employee"
    )


def test_R3_a_rejected_claim_does_not_block_the_same_data(client, db, org) -> None:
    same = {"type": "food", "amount": "321.00", "expense_date": _day(4).isoformat()}
    first = _claim(client, db, org, **same)
    _decide(client, org["mgr"]["h"], first["id"], "reject", rejection_reason="Wrong bill")
    assert _submit(client, db, org, **same).status_code == 201, "R3: rejected claims are not open"


def test_R3_the_database_itself_refuses_a_second_open_claim_on_one_receipt(client, db, org) -> None:
    ctx = org["ctx"]
    receipt = uuid.UUID(_receipt(db, ctx, org["emp"]["user"]))
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)

    def _row(amount: str, status: ReimbursementStatus) -> Reimbursement:
        return Reimbursement(
            company_id=ctx.company_id,
            employee_id=uuid.UUID(org["emp"]["id"]),
            type=ReimbursementType.food,
            amount=Decimal(amount),
            expense_date=_day(3),
            description="d",
            file_object_id=receipt,
            status=status,
        )

    db.add(_row("11.00", ReimbursementStatus.pending))
    db.flush()
    db.add(_row("12.00", ReimbursementStatus.approved))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_R3_the_database_itself_refuses_a_duplicate_open_claim(client, db, org) -> None:
    ctx = org["ctx"]
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)

    def _row(status: ReimbursementStatus) -> Reimbursement:
        return Reimbursement(
            company_id=ctx.company_id,
            employee_id=uuid.UUID(org["emp"]["id"]),
            type=ReimbursementType.food,
            amount=Decimal("99.00"),
            expense_date=_day(3),
            description="d",
            file_object_id=None,
            status=status,
        )

    db.add(_row(ReimbursementStatus.pending))
    db.flush()
    db.add(_row(ReimbursementStatus.pending))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_R3_a_rejected_row_does_not_count_for_the_database_index(client, db, org) -> None:
    ctx = org["ctx"]
    receipt = uuid.UUID(_receipt(db, ctx, org["emp"]["user"]))
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    for status in (ReimbursementStatus.rejected, ReimbursementStatus.pending):
        db.add(
            Reimbursement(
                company_id=ctx.company_id,
                employee_id=uuid.UUID(org["emp"]["id"]),
                type=ReimbursementType.food,
                amount=Decimal("55.00"),
                expense_date=_day(3),
                description="d",
                file_object_id=receipt,
                status=status,
            )
        )
        db.flush()


# --- simultaneous requests: a real engine, two threads, committed rows


def _race_world(engine) -> dict[str, Any]:
    cid = uuid.uuid4()
    with Session(engine) as setup:
        setup.add(
            Company(
                id=cid,
                name="Reimb Race Co",
                code=f"RRC{uuid.uuid4().hex[:4].upper()}",
                email=f"rrc-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
        )
        setup.flush()
        bind_tenant_to_session(setup, company_id=cid, is_platform_admin=False)
        setup.add(CompanySettings(company_id=cid))
        people: dict[str, Any] = {}
        for key, role in (
            ("emp", UserRole.employee),
            ("mgr", UserRole.manager),
            ("hr", UserRole.hr_admin),
        ):
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"{key}-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=role,
                is_active=True,
            )
            setup.add(user)
            setup.flush()
            employee = Employee(
                id=uuid.uuid4(),
                company_id=cid,
                user_id=user.id,
                employee_code=f"E{uuid.uuid4().hex[:6].upper()}",
                first_name=key,
                last_name="Race",
                email=user.email,
                employment_type=EmploymentType.full_time,
                hire_date=_day(400),
                is_active=True,
                invitation_status=InvitationStatus.activated,
            )
            setup.add(employee)
            setup.flush()
            token = create_access_token(sub=str(user.id), company_id=str(cid), role=role.value)
            people[key] = {
                "user": user.id,
                "employee": employee.id,
                "h": {"Authorization": f"Bearer {token}"},
            }
        emp_row = setup.get(Employee, people["emp"]["employee"])
        assert emp_row is not None
        emp_row.reporting_manager_id = people["mgr"]["employee"]
        receipts = []
        for _ in range(3):
            receipt = FileObject(
                company_id=cid,
                file_name="r.pdf",
                file_type=PDF,
                file_size=10,
                storage_path=f"/nowhere/{uuid.uuid4().hex}.pdf",
                uploaded_by=people["emp"]["user"],
            )
            setup.add(receipt)
            setup.flush()
            receipts.append(str(receipt.id))
        setup.commit()
    return {"cid": cid, "people": people, "receipts": receipts}


def _purge(cid: uuid.UUID) -> None:
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
            for table in (
                "reimbursements",
                "notifications",
                "audit_logs",
                "file_objects",
                "employees",
                "users",
                "company_settings",
            ):
                conn.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": cid})
            conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})
    finally:
        owner.dispose()


def _run_threads(workers: list) -> None:
    barrier = threading.Barrier(len(workers))

    def _wrap(fn):
        def _go() -> None:
            barrier.wait()
            fn()

        return _go

    threads = [threading.Thread(target=_wrap(w)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _use_real_sessions(engine) -> None:
    def _get_test_db():
        session = Session(engine)
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = _get_test_db


def _slow_create(monkeypatch: pytest.MonkeyPatch) -> None:
    original = ReimbursementRepository.create

    def _slow(self, **kwargs):  # noqa: ANN001, ANN003
        time.sleep(0.5)  # both requests passed their "already used?" look before either saves
        return original(self, **kwargs)

    monkeypatch.setattr(ReimbursementRepository, "create", _slow)


def _race_body(world_: dict[str, Any], receipt: int, **over: Any) -> dict[str, Any]:
    body = {
        "type": "food",
        "amount": "420.00",
        "expense_date": _day(3).isoformat(),
        "description": "Race lunch",
        "file_object_id": world_["receipts"][receipt],
    }
    body.update(over)
    return body


def test_R3_two_simultaneous_claims_on_one_receipt_give_one_201_and_one_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _slow_create(monkeypatch)
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    race = _race_world(engine)
    try:
        _use_real_sessions(engine)
        results: list[int] = []

        def _worker(amount: str):
            def _go() -> None:
                c = TestClient(fastapi_app)
                body = _race_body(race, 0, amount=amount)  # same receipt, different amounts
                results.append(
                    c.post(BASE, json=body, headers=race["people"]["emp"]["h"]).status_code
                )

            return _go

        _run_threads([_worker("420.00"), _worker("421.00")])
        assert 500 not in results, f"R3: a race must never give a 500: {results}"
        assert sorted(results) == [201, 409], f"R3: expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge(race["cid"])


def test_R3_two_simultaneous_identical_claims_with_different_receipts_give_one_201_and_one_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _slow_create(monkeypatch)
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    race = _race_world(engine)
    try:
        _use_real_sessions(engine)
        results: list[int] = []

        def _worker(receipt: int):
            def _go() -> None:
                c = TestClient(fastapi_app)
                body = _race_body(race, receipt)  # same date, type and amount
                results.append(
                    c.post(BASE, json=body, headers=race["people"]["emp"]["h"]).status_code
                )

            return _go

        _run_threads([_worker(0), _worker(1)])
        assert 500 not in results, f"R3: a race must never give a 500: {results}"
        assert sorted(results) == [201, 409], f"R3: expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge(race["cid"])


# ------------------------------------------------------------------- R4


def test_R4_an_employee_sees_only_their_own_claims(client, db, org) -> None:
    mine = _claim(client, db, org, "emp")
    _claim(client, db, org, "peer")
    _claim(client, db, org, "mgr")
    assert _ids(_list(client, org["emp"]["h"])) == [mine["id"]], "R4: an employee sees only own"


def test_R4_a_manager_sees_own_and_direct_reports_claims_only(client, db, org) -> None:
    own = _claim(client, db, org, "mgr")
    emp_c = _claim(client, db, org, "emp")
    peer_c = _claim(client, db, org, "peer")
    boss_c = _claim(client, db, org, "boss")
    other_c = _claim(client, db, org, "other_mgr")
    seen = set(_ids(_list(client, org["mgr"]["h"])))
    assert seen == {own["id"], emp_c["id"], peer_c["id"]}, f"R4: manager sees own + team: {seen}"
    assert boss_c["id"] not in seen and other_c["id"] not in seen, "R4: not their boss or outsiders"
    boss_seen = set(_ids(_list(client, org["boss"]["h"])))
    assert boss_seen == {boss_c["id"], own["id"]}, (
        f"R4: team means direct reports only, not reports of reports: {boss_seen}"
    )


def test_R4_hr_admin_and_owner_see_every_claim_in_the_company(client, db, org) -> None:
    made = {_claim(client, db, org, w)["id"] for w in ("emp", "peer", "mgr", "other_mgr")}
    for who in ("hr", "hr2", "owner"):
        assert set(_ids(_list(client, org[who]))) == made, f"R4: {who} must see all claims"


def test_R4_another_companys_claims_never_appear(client, db, org, company_b) -> None:
    theirs = _foreign_claim(client, db, company_b)
    mine = _claim(client, db, org, "emp")
    for who in ("hr", "owner"):
        ids = _ids(_list(client, org[who]))
        assert theirs["id"] not in ids and mine["id"] in ids, f"R4: {who} sees a foreign claim"
    assert _ids(_list(client, company_b.hr_headers)) == [theirs["id"]], "R4: B sees only B's"


def test_R4_a_user_without_a_profile_gets_an_empty_page(client, db, org) -> None:
    _claim(client, db, org, "emp")
    resp = _list(client, org["ctx"].employee_headers)
    assert resp.status_code == 200 and resp.json()["items"] == [], resp.text


def test_R4_the_list_is_newest_first_and_paged(client, db, org) -> None:
    made = [_claim(client, db, org, "emp") for _ in range(5)]
    for index, claim in enumerate(made):
        _force(db, org["ctx"], claim["id"], created_at=utcnow() - timedelta(minutes=50 - index))
    newest_first = [c["id"] for c in reversed(made)]
    assert _ids(_list(client, org["emp"]["h"])) == newest_first, "R4: newest first"
    page1 = _list(client, org["emp"]["h"], "?limit=2&page=1").json()
    page2 = _list(client, org["emp"]["h"], "?limit=2&page=2").json()
    page3 = _list(client, org["emp"]["h"], "?limit=2&page=3").json()
    assert [c["id"] for c in page1["items"]] == newest_first[0:2]
    assert [c["id"] for c in page2["items"]] == newest_first[2:4]
    assert [c["id"] for c in page3["items"]] == newest_first[4:5]
    assert (page1["total"], page1["pages"], page1["has_next"]) == (5, 3, True), page1
    assert page3["has_next"] is False, "R4: the last page has no next"


def test_R4_the_status_filter(client, db, org) -> None:
    a = _claim(client, db, org, "emp")
    b = _claim(client, db, org, "emp")
    _decide(client, org["mgr"]["h"], b["id"])
    assert _ids(_list(client, org["emp"]["h"], "?status=pending")) == [a["id"]]
    assert _ids(_list(client, org["emp"]["h"], "?status=approved")) == [b["id"]]
    assert _ids(_list(client, org["emp"]["h"], "?status=withdrawn")) == []


def test_R4_the_employee_filter_stays_inside_what_the_caller_may_see(client, db, org) -> None:
    emp_c = _claim(client, db, org, "emp")
    other_c = _claim(client, db, org, "other_mgr")
    assert _ids(_list(client, org["hr"], f"?employee_id={org['emp']['id']}")) == [emp_c["id"]]
    assert _ids(_list(client, org["mgr"]["h"], f"?employee_id={org['emp']['id']}")) == [emp_c["id"]]
    assert _ids(_list(client, org["mgr"]["h"], f"?employee_id={org['other_mgr']['id']}")) == [], (
        "R4: a manager filtering by someone outside the team sees nothing"
    )
    assert other_c["id"] in _ids(_list(client, org["hr"])), "R4: HR still sees the other claim"


def test_R4_the_month_and_year_filters_use_the_expense_date(client, db, org) -> None:
    recent = _claim(client, db, org, "emp", expense_date=_day(5).isoformat())
    old = _claim(client, db, org, "emp", expense_date=_day(60).isoformat())
    for claim_day, claim in ((_day(5), recent), (_day(60), old)):
        got = _ids(
            _list(client, org["emp"]["h"], f"?month={claim_day.month}&year={claim_day.year}")
        )
        assert claim["id"] in got, f"R4: the month/year filter lost {claim_day}"
    only_year = _ids(_list(client, org["emp"]["h"], f"?year={_day(5).year}"))
    assert recent["id"] in only_year, "R4: the year filter alone must work"
    far = _list(client, org["emp"]["h"], "?month=1&year=2001")
    assert far.status_code == 200 and far.json()["items"] == [], "R4: nothing in 2001"


@pytest.mark.parametrize(
    "query",
    [
        "?status=bogus",
        "?employee_id=not-a-uuid",
        "?month=0",
        "?month=13",
        "?year=1999",
        "?year=2101",
        "?page=0",
        "?limit=0",
        "?limit=101",
        "?month=abc",
    ],
)
def test_R4_bad_ids_and_filters_give_422(client, db, org, query) -> None:
    resp = _list(client, org["emp"]["h"], query)
    assert resp.status_code == 422, f"R4: {query} must give 422: {resp.text}"


def test_R4_a_claim_has_exactly_the_documented_fields(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    assert set(claim) == {
        "id",
        "employee_id",
        "type",
        "amount",
        "expense_date",
        "description",
        "file_object_id",
        "status",
        "approved_by",
        "approved_at",
        "rejection_reason",
        "added_to_payroll_run_id",
        "created_at",
    }, f"R4: response fields changed: {sorted(claim)}"


# ------------------------------------------------------------------- R5


@pytest.mark.parametrize("approver", ["mgr", "boss"])
def test_R5_the_direct_manager_and_anyone_above_in_the_chain_can_decide(
    client, db, org, approver
) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(client, org[approver]["h"], claim["id"])
    assert resp.status_code == 200, f"R5: {approver} is in the chain and must approve: {resp.text}"
    assert resp.json()["approved_by"] == str(org[approver]["user"].id), "R5: approver recorded"


@pytest.mark.parametrize("approver", ["hr", "hr2", "owner"])
def test_R5_hr_level_can_decide_anyones_claim(client, db, org, approver) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(client, org[approver], claim["id"])
    assert resp.status_code == 200, f"R5: {approver} must approve: {resp.text}"


def test_R5_an_outsider_an_employee_and_a_manager_outside_the_chain_get_the_same_403(
    client, db, org
) -> None:
    claim = _claim(client, db, org, "emp")
    ctx = org["ctx"]
    callers = {
        "manager outside the chain": org["other_mgr"]["h"],
        "colleague employee": org["peer"]["h"],
        "the claimant's own employee role": org["emp"]["h"],
        "user without a profile": ctx.employee_headers,
        "manager without a profile": ctx.manager_headers,
    }
    messages = set()
    for label, headers in callers.items():
        resp = _decide(client, headers, claim["id"])
        assert resp.status_code == 403, f"R5: {label} must get 403: {resp.text}"
        messages.add(_message(resp))
    assert len(messages) == 1, f"R5: all refusals must carry the same message: {messages}"
    assert _state(db, ctx, claim["id"]).status == ReimbursementStatus.pending, "R5: unchanged"


def test_R5_a_refused_reject_changes_nothing(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(client, org["other_mgr"]["h"], claim["id"], "reject", rejection_reason="No")
    assert resp.status_code == 403, resp.text
    row = _state(db, org["ctx"], claim["id"])
    assert row.status == ReimbursementStatus.pending and row.rejection_reason is None


@pytest.mark.parametrize("who", ["mgr", "hr_emp", "emp"])
def test_R5_nobody_but_an_owner_decides_their_own_claim(client, db, org, who) -> None:
    claim = _claim(client, db, org, who)
    resp = _decide(client, org[who]["h"], claim["id"])
    assert resp.status_code == 403, f"R5: {who} must not approve their own claim: {resp.text}"
    assert _state(db, org["ctx"], claim["id"]).status == ReimbursementStatus.pending


def test_R5_an_owner_may_decide_their_own_claim(client, db, org) -> None:
    claim = _claim(client, db, org, "owner_emp")
    resp = _decide(client, org["owner_emp"]["h"], claim["id"])
    assert resp.status_code == 200, f"R5: an owner may approve their own claim: {resp.text}"


def test_R5_another_companys_claim_and_a_missing_claim_give_the_same_404(
    client, db, org, company_b
) -> None:
    theirs = _foreign_claim(client, db, company_b)
    responses = [
        _decide(client, org["hr"], theirs["id"]),
        _decide(client, org["owner"], theirs["id"]),
        _decide(client, org["mgr"]["h"], theirs["id"]),
        _decide(client, org["hr"], str(uuid.uuid4())),
        _decide(client, org["mgr"]["h"], str(uuid.uuid4())),
    ]
    assert [r.status_code for r in responses] == [404] * 5, [r.text for r in responses]
    assert len({_message(r) for r in responses}) == 1, "R5: one message for foreign and missing"
    assert _state(db, company_b, theirs["id"]).status == ReimbursementStatus.pending


# ------------------------------------------------------------------- R6


def test_R6_approving_records_who_and_when(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(client, org["mgr"]["h"], claim["id"])
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "approved", resp.text
    assert body["approved_by"] == str(org["mgr"]["user"].id), "R6: approver recorded"
    assert body["approved_at"] is not None, "R6: decision time recorded"
    assert body["rejection_reason"] is None, "R6: an approval has no reason"


def test_R6_rejecting_stores_the_trimmed_reason(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(
        client, org["mgr"]["h"], claim["id"], "reject", rejection_reason="  Not in policy "
    )
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "rejected", resp.text
    assert body["rejection_reason"] == "Not in policy", "R6: the reason must be trimmed"
    assert body["approved_by"] == str(org["mgr"]["user"].id), "R6: decider recorded"


@pytest.mark.parametrize("reason", [None, "", "   ", "x" * 501])
def test_R6_a_rejection_needs_a_reason_of_1_to_500_characters(client, db, org, reason) -> None:
    claim = _claim(client, db, org, "emp")
    body: dict[str, Any] = {"action": "reject"}
    if reason is not None:
        body["rejection_reason"] = reason
    resp = client.put(f"{BASE}/{claim['id']}", json=body, headers=org["mgr"]["h"])
    assert resp.status_code == 422, f"R6: reason {str(reason)[:5]!r} must give 422: {resp.text}"
    assert "rejection_reason" in _fields(resp), "R6: the error must name rejection_reason"
    assert _state(db, org["ctx"], claim["id"]).status == ReimbursementStatus.pending


def test_R6_a_500_character_reason_is_allowed(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(client, org["mgr"]["h"], claim["id"], "reject", rejection_reason="x" * 500)
    assert resp.status_code == 200, resp.text


def test_R6_approving_takes_no_reason(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _decide(client, org["mgr"]["h"], claim["id"], "approve", rejection_reason="why")
    assert resp.status_code == 422, f"R6: an approval with a reason must give 422: {resp.text}"
    assert _state(db, org["ctx"], claim["id"]).status == ReimbursementStatus.pending


@pytest.mark.parametrize(
    "body", [{"action": "pay"}, {"action": ""}, {}, {"action": "approve", "x": 1}]
)
def test_R6_a_bad_decision_body_gives_422(client, db, org, body) -> None:
    claim = _claim(client, db, org, "emp")
    resp = client.put(f"{BASE}/{claim['id']}", json=body, headers=org["mgr"]["h"])
    assert resp.status_code == 422, f"R6: body {body} must give 422: {resp.text}"


def test_R6_a_bad_claim_id_gives_422(client, db, org) -> None:
    resp = client.put(f"{BASE}/not-a-uuid", json={"action": "approve"}, headers=org["mgr"]["h"])
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "first,second",
    [("approve", "approve"), ("approve", "reject"), ("reject", "approve"), ("reject", "reject")],
)
def test_R6_a_decision_is_made_once(client, db, org, first, second) -> None:
    claim = _claim(client, db, org, "emp")
    extra = {"rejection_reason": "No"} if first == "reject" else {}
    assert _decide(client, org["mgr"]["h"], claim["id"], first, **extra).status_code == 200
    extra = {"rejection_reason": "No"} if second == "reject" else {}
    again = _decide(client, org["boss"]["h"], claim["id"], second, **extra)
    assert again.status_code == 409, f"R6: {first} then {second} must give 409: {again.text}"
    assert "not pending" in _message(again), _message(again)


def test_R6_a_paid_claim_cannot_be_decided(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    _force(db, org["ctx"], claim["id"], status=ReimbursementStatus.paid)
    resp = _decide(client, org["hr"], claim["id"])
    assert resp.status_code == 409, f"R6: a paid claim must give 409: {resp.text}"


def test_R6_the_decision_and_its_audit_row_and_notification_are_one_save(
    client, db, org, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = _claim(client, db, org, "emp")
    bind_tenant_to_session(db, company_id=org["ctx"].company_id, is_platform_admin=False)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditService, "record", _boom)
    from app.modules.payroll.schemas import ReimbursementReviewRequest

    with pytest.raises(RuntimeError):
        ReimbursementService(db).review_claim(
            org["ctx"].company_id,
            uuid.UUID(claim["id"]),
            ReimbursementReviewRequest(action="approve"),
            org["mgr"]["user"],
        )
    db.rollback()
    assert _state(db, org["ctx"], claim["id"]).status == ReimbursementStatus.pending, (
        "R6: the decision was saved although its audit row failed"
    )


def _decision_race_world(monkeypatch: pytest.MonkeyPatch):
    original = ReimbursementRepository.update

    def _slow_update(self, claim, **kwargs):  # noqa: ANN001, ANN003
        if "status" in kwargs:
            time.sleep(0.5)  # both requests have read "pending" before either one saves
        return original(self, claim, **kwargs)

    monkeypatch.setattr(ReimbursementRepository, "update", _slow_update)
    assert settings.TEST_DATABASE_URL is not None
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    race = _race_world(engine)
    with Session(engine) as session:
        bind_tenant_to_session(session, company_id=race["cid"], is_platform_admin=False)
        claim = Reimbursement(
            company_id=race["cid"],
            employee_id=race["people"]["emp"]["employee"],
            type=ReimbursementType.food,
            amount=Decimal("300.00"),
            expense_date=_day(3),
            description="d",
            file_object_id=uuid.UUID(race["receipts"][0]),
            status=ReimbursementStatus.pending,
        )
        session.add(claim)
        session.commit()
        race["claim"] = str(claim.id)
    _use_real_sessions(engine)
    return engine, race


def test_R6_two_simultaneous_decisions_give_one_200_and_one_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, race = _decision_race_world(monkeypatch)
    try:
        results: list[int] = []

        def _worker(who: str):
            def _go() -> None:
                c = TestClient(fastapi_app)
                results.append(_decide(c, race["people"][who]["h"], race["claim"]).status_code)

            return _go

        _run_threads([_worker("mgr"), _worker("hr")])
        assert 500 not in results, f"R6: a race must never give a 500: {results}"
        assert sorted(results) == [200, 409], f"R6: expected one 200 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge(race["cid"])


# ------------------------------------------------------------------- R7


def test_R7_the_claimant_withdraws_their_pending_claim(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    resp = _withdraw(client, org["emp"]["h"], claim["id"])
    assert resp.status_code == 200, f"R7: withdraw: {resp.text}"
    assert resp.json()["status"] == "withdrawn", f"R7: status must be withdrawn: {resp.text}"
    assert _state(db, org["ctx"], claim["id"]).status == ReimbursementStatus.withdrawn


def test_R7_a_withdrawn_claim_cannot_be_decided_or_withdrawn_again(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    _withdraw(client, org["emp"]["h"], claim["id"])
    assert _decide(client, org["mgr"]["h"], claim["id"]).status_code == 409, "R7: decide"
    assert _withdraw(client, org["emp"]["h"], claim["id"]).status_code == 409, "R7: twice"


@pytest.mark.parametrize("setup", ["approved", "rejected", "paid", "in_run"])
def test_R7_a_decided_paid_or_in_run_claim_cannot_be_withdrawn(client, db, org, setup) -> None:
    claim = _claim(client, db, org, "emp")
    if setup == "approved":
        _decide(client, org["mgr"]["h"], claim["id"])
    elif setup == "rejected":
        _decide(client, org["mgr"]["h"], claim["id"], "reject", rejection_reason="No")
    elif setup == "paid":
        _force(db, org["ctx"], claim["id"], status=ReimbursementStatus.paid)
    else:
        _decide(client, org["mgr"]["h"], claim["id"])
        run_id = _make_run_row(db, org["ctx"], org["hr_emp"]["user"])
        _force(db, org["ctx"], claim["id"], added_to_payroll_run_id=run_id)
    resp = _withdraw(client, org["emp"]["h"], claim["id"])
    assert resp.status_code == 409, f"R7: a {setup} claim must give 409: {resp.text}"
    assert _state(db, org["ctx"], claim["id"]).status != ReimbursementStatus.withdrawn


def _make_run_row(db: Session, ctx: TenantContext, user: User) -> uuid.UUID:
    from app.modules.payroll.models import PayrollRun, PayrollRunStatus, PayrollRunType

    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    run = PayrollRun(
        company_id=ctx.company_id,
        month=1,
        year=2001,
        status=PayrollRunStatus.pending_approval,
        run_type=PayrollRunType.off_cycle,
        idempotency_key=f"k-{uuid.uuid4()}",
        run_by=user.id,
    )
    db.add(run)
    db.commit()
    return run.id


@pytest.mark.parametrize("who", ["peer", "mgr", "boss", "hr", "owner"])
def test_R7_only_the_claimant_can_withdraw_everyone_else_gets_the_same_403(
    client, db, org, who
) -> None:
    claim = _claim(client, db, org, "emp")
    headers = org[who]["h"] if isinstance(org[who], dict) and "h" in org[who] else org[who]
    resp = _withdraw(client, headers, claim["id"])
    assert resp.status_code == 403, f"R7: {who} must get 403: {resp.text}"
    assert _message(resp) == "Only the person who made the claim can withdraw it.", _message(resp)
    assert _state(db, org["ctx"], claim["id"]).status == ReimbursementStatus.pending


def test_R7_another_companys_claim_and_a_missing_claim_give_the_same_404(
    client, db, org, company_b
) -> None:
    theirs = _foreign_claim(client, db, company_b)
    responses = [
        _withdraw(client, org["emp"]["h"], theirs["id"]),
        _withdraw(client, org["hr"], theirs["id"]),
        _withdraw(client, org["emp"]["h"], str(uuid.uuid4())),
    ]
    assert [r.status_code for r in responses] == [404] * 3, [r.text for r in responses]
    assert {_message(r) for r in responses} == {"Reimbursement claim not found."}, (
        f"R7: one message for foreign and missing: {[_message(r) for r in responses]}"
    )


def test_R7_a_bad_claim_id_gives_422(client, db, org) -> None:
    assert _withdraw(client, org["emp"]["h"], "not-a-uuid").status_code == 422


def test_R7_withdraw_frees_the_receipt_and_the_duplicate_check(client, db, org) -> None:
    same = {"type": "food", "amount": "654.00", "expense_date": _day(4).isoformat()}
    claim = _claim(client, db, org, "emp", **same)
    withdrawn = _withdraw(client, org["emp"]["h"], claim["id"])
    assert withdrawn.status_code == 200, f"R7: the claim must be withdrawn first: {withdrawn.text}"
    assert _submit(client, db, org, "emp", **same).status_code == 201, "R7: data is free again"


def test_R7_the_status_enum_has_the_new_value_in_the_database(db) -> None:
    labels = {
        r[0]
        for r in db.execute(
            text("SELECT unnest(enum_range(NULL::reimbursement_status))::text")
        ).fetchall()
    }
    assert labels == {"pending", "approved", "rejected", "paid", "withdrawn"}, labels


def test_R7_a_withdraw_and_an_approval_at_the_same_moment_give_one_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, race = _decision_race_world(monkeypatch)
    try:
        results: list[int] = []

        def _approve() -> None:
            c = TestClient(fastapi_app)
            results.append(_decide(c, race["people"]["mgr"]["h"], race["claim"]).status_code)

        def _withdraw_it() -> None:
            c = TestClient(fastapi_app)
            results.append(_withdraw(c, race["people"]["emp"]["h"], race["claim"]).status_code)

        _run_threads([_approve, _withdraw_it])
        assert 500 not in results, f"R7: a race must never give a 500: {results}"
        assert sorted(results) == [200, 409], f"R7: expected one 200 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge(race["cid"])


# ------------------------------------------------------------------- R8


def _world_claim(client, db, w: dict[str, Any], amount: str, who: str = "emp") -> str:
    """A claim by a person of the 5.4 `world`, approved by HR."""
    ctx = w["ctx"]
    org_like = {"ctx": ctx, who: w[who]}
    made = _claim(client, db, org_like, who, amount=amount, expense_date=_day(40).isoformat())
    resp = _decide(client, w["hr1"], made["id"])
    assert resp.status_code == 200, resp.text
    return made["id"]


def test_R8_a_claim_joins_one_run_stays_approved_until_the_run_is_approved_then_is_paid(
    client, db, world
) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    claim_id = _world_claim(client, db, world, "2500.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    row = _state(db, ctx, claim_id)
    assert row.status == ReimbursementStatus.approved, "R8: not paid before the run is approved"
    assert str(row.added_to_payroll_run_id) == run["id"], "R8: the claim joined the run"
    item = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    assert item["reimbursement_amount"] == "2500.00", "R8: the item pays exactly the claim"
    client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    row = _state(db, ctx, claim_id)
    assert row.status == ReimbursementStatus.paid, "R8: paid when the run is approved"
    assert str(row.added_to_payroll_run_id) == run["id"], "R8: still the same run"


def test_R8_the_paid_amount_is_the_sum_of_the_claims_of_that_employee(client, db, world) -> None:
    _filled_world(db, world)
    _world_claim(client, db, world, "1000.50")
    _world_claim(client, db, world, "249.25")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    item = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    assert item["reimbursement_amount"] == "1249.75", f"R8: sum wrong: {item}"
    other = _item_for(client, world["hr1"], run["id"], world["manager"]["id"])
    assert other["reimbursement_amount"] == "0.00", "R8: nobody else is paid this"


def test_R8_a_claim_joins_at_most_one_run(client, db, world) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    claim_id = _world_claim(client, db, world, "700.00")
    first = _make_run(client, world["hr1"], world["year"], world["month"])
    off = client.post(
        RUNS,
        json={"month": world["month"], "year": world["year"], "run_type": "off_cycle"},
        headers={**world["hr1"], "Idempotency-Key": f"off-{uuid.uuid4()}"},
    )
    assert off.status_code == 202, off.text
    again = _item_for(client, world["hr1"], off.json()["id"], world["emp"]["id"])
    assert again["reimbursement_amount"] == "0.00", "R8: a locked claim must not join a second run"
    assert str(_state(db, ctx, claim_id).added_to_payroll_run_id) == first["id"]


def test_R8_a_claim_is_never_added_to_taxable_pay(client, db, world) -> None:
    _filled_world(db, world)
    _world_claim(client, db, world, "5000.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    with_claim = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    without = _item_for(client, world["hr1"], run["id"], world["manager"]["id"])
    assert with_claim["gross_salary"] == without["gross_salary"], "R8: gross must not include it"
    assert with_claim["total_deductions"] == without["total_deductions"], "R8: no extra tax/PF"
    assert with_claim["earnings_json"] == without["earnings_json"], "R8: not an earning line"
    net_gap = Decimal(with_claim["net_salary"]) - Decimal(without["net_salary"])
    assert net_gap == Decimal("5000.00"), f"R8: net pay rises by exactly the claim: {net_gap}"


def test_R8_pending_rejected_and_withdrawn_claims_never_join_a_run(client, db, world) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    org_like = {"ctx": ctx, "emp": world["emp"]}
    pending = _claim(
        client, db, org_like, "emp", amount="101.00", expense_date=_day(40).isoformat()
    )
    rejected = _claim(
        client, db, org_like, "emp", amount="102.00", expense_date=_day(40).isoformat()
    )
    _decide(client, world["hr1"], rejected["id"], "reject", rejection_reason="No")
    withdrawn = _claim(
        client, db, org_like, "emp", amount="103.00", expense_date=_day(40).isoformat()
    )
    _withdraw(client, world["emp"]["h"], withdrawn["id"])
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    item = _item_for(client, world["hr1"], run["id"], world["emp"]["id"])
    assert item["reimbursement_amount"] == "0.00", f"R8: only approved claims are paid: {item}"
    for claim in (pending, rejected, withdrawn):
        assert _state(db, ctx, claim["id"]).added_to_payroll_run_id is None


def test_R8_deleting_an_unapproved_run_releases_its_claims(client, db, world) -> None:
    _filled_world(db, world)
    ctx = world["ctx"]
    claim_id = _world_claim(client, db, world, "800.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    assert _state(db, ctx, claim_id).added_to_payroll_run_id is not None
    assert client.delete(f"{RUNS}/{run['id']}", headers=world["hr2"]).status_code == 204
    row = _state(db, ctx, claim_id)
    assert row.added_to_payroll_run_id is None and row.status == ReimbursementStatus.approved, (
        "R8: the claim must be released and still approved"
    )
    again = _make_run(client, world["hr1"], world["year"], world["month"])
    item = _item_for(client, world["hr1"], again["id"], world["emp"]["id"])
    assert item["reimbursement_amount"] == "800.00", "R8: the released claim is paid next time"


@pytest.mark.parametrize("stage", ["in_unapproved_run", "in_approved_run"])
def test_R8_a_claim_in_a_run_cannot_be_decided_or_withdrawn(client, db, world, stage) -> None:
    _filled_world(db, world)
    claim_id = _world_claim(client, db, world, "900.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    if stage == "in_approved_run":
        client.post(f"{RUNS}/{run['id']}/approve", headers=world["owner"])
    for label, resp in (
        ("approve", _decide(client, world["hr2"], claim_id)),
        ("reject", _decide(client, world["hr2"], claim_id, "reject", rejection_reason="Late")),
        ("withdraw", _withdraw(client, world["emp"]["h"], claim_id)),
    ):
        assert resp.status_code == 409, f"R8: {label} in {stage} must give 409: {resp.text}"
    row = _state(db, world["ctx"], claim_id)
    assert (
        row.status != ReimbursementStatus.withdrawn and row.status != ReimbursementStatus.rejected
    )


def test_R8_approving_the_run_twice_pays_a_claim_once(client, db, world) -> None:
    _filled_world(db, world)
    claim_id = _world_claim(client, db, world, "1200.00")
    run = _make_run(client, world["hr1"], world["year"], world["month"])
    for who in ("owner", "hr2", "owner"):
        client.post(f"{RUNS}/{run['id']}/approve", headers=world[who])
    assert _state(db, world["ctx"], claim_id).status == ReimbursementStatus.paid
    detail = client.get(f"{RUNS}/{run['id']}", headers=world["hr1"]).json()
    paid = [
        i["reimbursement_amount"] for i in detail["items"] if i["employee_id"] == world["emp"]["id"]
    ]
    assert paid == ["1200.00"], f"R8: the claim is paid once in the run: {paid}"


# ------------------------------------------------------------------- R9


def test_R9_submitting_writes_one_audit_row_with_ids_type_and_status_only(client, db, org) -> None:
    claim = _claim(client, db, org, "emp", description="Secret dinner with Mr X")
    rows = _audit(db, org["ctx"], "REIMBURSEMENT_SUBMITTED")
    assert len(rows) == 1, f"R9: one submit must write one audit row, got {len(rows)}"
    row = rows[0]
    assert str(row.entity_id) == claim["id"] and row.entity_type == "reimbursement"
    assert row.actor_user_id == org["emp"]["user"].id, "R9: the actor is the claimant"
    assert set(row.details) <= {"employee_id", "type", "status"}, f"R9: details: {row.details}"
    shown = str(row.details)
    for secret in ("Secret dinner", "private-receipt-name", claim["amount"]):
        assert secret not in shown, f"R9: the audit row holds {secret}"
    assert _audit(db, org["ctx"], "REIMBURSEMENT_CLAIM_SUBMITTED") == [], "R9: old action name"


def test_R9_approving_and_rejecting_each_write_one_audit_row(client, db, org) -> None:
    a = _claim(client, db, org, "emp")
    b = _claim(client, db, org, "emp")
    _decide(client, org["mgr"]["h"], a["id"])
    _decide(client, org["mgr"]["h"], b["id"], "reject", rejection_reason="Private reason text")
    approved = _audit(db, org["ctx"], "REIMBURSEMENT_APPROVED")
    rejected = _audit(db, org["ctx"], "REIMBURSEMENT_REJECTED")
    assert [str(r.entity_id) for r in approved] == [a["id"]], "R9: one approved row"
    assert [str(r.entity_id) for r in rejected] == [b["id"]], "R9: one rejected row"
    for row in approved + rejected:
        assert row.actor_user_id == org["mgr"]["user"].id, "R9: the actor is the decider"
        assert set(row.details) <= {"employee_id", "type", "status"}, f"R9: {row.details}"
        assert "Private reason text" not in str(row.details), "R9: the reason is in the audit row"


def test_R9_withdrawing_writes_one_audit_row(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    _withdraw(client, org["emp"]["h"], claim["id"])
    rows = _audit(db, org["ctx"], "REIMBURSEMENT_WITHDRAWN")
    assert [str(r.entity_id) for r in rows] == [claim["id"]], "R9: one withdrawn row"
    assert rows[0].actor_user_id == org["emp"]["user"].id


def test_R9_refused_requests_write_no_audit_row(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    _decide(client, org["other_mgr"]["h"], claim["id"])
    _withdraw(client, org["peer"]["h"], claim["id"])
    _submit(client, db, org, amount="0")
    for action in ("REIMBURSEMENT_APPROVED", "REIMBURSEMENT_REJECTED", "REIMBURSEMENT_WITHDRAWN"):
        assert _audit(db, org["ctx"], action) == [], f"R9: a refused request wrote {action}"
    assert len(_audit(db, org["ctx"], "REIMBURSEMENT_SUBMITTED")) == 1


def test_R9_the_claim_and_its_audit_row_are_one_save(
    db, org, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.payroll.schemas import ReimbursementCreateRequest

    ctx = org["ctx"]
    body = ReimbursementCreateRequest(
        **{**_body(db, org), "file_object_id": uuid.UUID(_receipt(db, ctx, org["emp"]["user"]))}
    )

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit failed")

    monkeypatch.setattr(AuditService, "record", _boom)
    with pytest.raises(RuntimeError):
        ReimbursementService(db).submit_claim(ctx.company_id, body, org["emp"]["user"])
    db.rollback()
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    assert db.query(Reimbursement).count() == 0, "R9: the claim was saved without its audit row"


def test_R9_the_chain_is_notified_when_a_claim_is_submitted(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    ctx = org["ctx"]
    for who in ("mgr", "boss"):
        notes = _notes(db, ctx, org[who]["user"], "reimbursement_submitted")
        assert [str(n.entity_id) for n in notes] == [claim["id"]], f"R9: {who} must be told"
        assert notes[0].action_url == "/payroll/reimbursements", "R9: link to the claims page"
    for who in ("peer", "other_mgr", "emp"):
        assert _notes(db, ctx, org[who]["user"], "reimbursement_submitted") == [], (
            f"R9: {who} is not in the chain and must not be told"
        )


def test_R9_the_employee_is_notified_of_a_decision_without_the_reason(client, db, org) -> None:
    a = _claim(client, db, org, "emp")
    b = _claim(client, db, org, "emp")
    _decide(client, org["mgr"]["h"], a["id"])
    _decide(client, org["mgr"]["h"], b["id"], "reject", rejection_reason="Hidden reason text")
    ctx = org["ctx"]
    approved = _notes(db, ctx, org["emp"]["user"], "reimbursement_approved")
    rejected = _notes(db, ctx, org["emp"]["user"], "reimbursement_rejected")
    assert [str(n.entity_id) for n in approved] == [a["id"]], "R9: approval notice"
    assert [str(n.entity_id) for n in rejected] == [b["id"]], "R9: rejection notice"
    for note in approved + rejected:
        assert "Hidden reason text" not in f"{note.title} {note.message}", "R9: reason in notice"
    assert _notes(db, ctx, org["peer"]["user"]) == [], "R9: nobody else is told"


def test_R9_a_refused_decision_sends_no_notification(client, db, org) -> None:
    claim = _claim(client, db, org, "emp")
    _decide(client, org["other_mgr"]["h"], claim["id"])
    assert _notes(db, org["ctx"], org["emp"]["user"]) == [], "R9: a refused decision told someone"


def test_R9_submit_is_limited_to_10_per_minute_per_user(client, db, org, limits_on) -> None:
    bodies = [_body(db, org) for _ in range(11)]
    codes = [client.post(BASE, json=b, headers=org["emp"]["h"]).status_code for b in bodies]
    assert codes[:10] == [201] * 10 and codes[10] == 429, f"R9: submit limit wrong: {codes}"
    other = _submit(client, db, org, "peer")
    assert other.status_code == 201, "R9: the limit is per user"


def test_R9_review_is_limited_to_10_per_minute_per_user(client, db, org, limits_on) -> None:
    codes = [_decide(client, org["mgr"]["h"], str(uuid.uuid4())).status_code for _ in range(11)]
    assert codes[:10] == [404] * 10 and codes[10] == 429, f"R9: review limit wrong: {codes}"


def test_R9_withdraw_is_limited_to_10_per_minute_per_user(client, db, org, limits_on) -> None:
    codes = [_withdraw(client, org["emp"]["h"], str(uuid.uuid4())).status_code for _ in range(11)]
    assert codes[:10] == [404] * 10 and codes[10] == 429, f"R9: withdraw limit wrong: {codes}"


def test_R9_the_list_is_limited_to_60_per_minute_per_user(client, db, org, limits_on) -> None:
    codes = [_list(client, org["emp"]["h"]).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429, f"R9: list limit wrong: {codes[-3:]}"
    assert _list(client, org["peer"]["h"]).status_code == 200, "R9: the limit is per user"


# ------------------------------------------------------------------- R10


def test_R10_the_models_and_the_migrations_agree_on_reimbursements() -> None:
    """What `alembic check` does in CI, for the table this package changed."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.base import Base

    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with engine.connect() as conn:
            diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    mine = [d for d in diffs if "reimbursements" in str(d)]
    assert mine == [], f"R10: models and migrations differ: {mine}"


def test_R10_the_database_has_the_two_partial_unique_indexes_and_the_receipt_key(db) -> None:
    names = {i["name"] for i in inspect(db.get_bind()).get_indexes("reimbursements")}
    assert {"uq_reimbursements_open_receipt", "uq_reimbursements_open_claim"} <= names, names
    keys = inspect(db.get_bind()).get_foreign_keys("reimbursements")
    assert any(k["referred_table"] == "file_objects" for k in keys), "R10: receipt foreign key"


def _cfg() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _previous_revision() -> str:
    revision = ScriptDirectory.from_config(_cfg()).get_revision(MIGRATION_REVISION)
    assert revision is not None and isinstance(revision.down_revision, str)
    return revision.down_revision


def _orm_company_with_employee(engine) -> tuple[uuid.UUID, uuid.UUID]:
    cid = uuid.uuid4()
    with Session(engine) as sess:
        sess.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        sess.add(
            Company(
                id=cid,
                name="Reimb Mig Co",
                code=f"RMC{uuid.uuid4().hex[:4].upper()}",
                email=f"rmc-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
                is_active=True,
            )
        )
        sess.flush()
        emp = Employee(
            id=uuid.uuid4(),
            company_id=cid,
            employee_code=f"E{uuid.uuid4().hex[:6].upper()}",
            first_name="Mig",
            last_name="Rate",
            email=f"mig-{uuid.uuid4().hex[:6]}@example.com",
            hire_date=_day(400),
            is_active=True,
        )
        sess.add(emp)
        sess.flush()
        emp_id = emp.id
        sess.commit()
        return cid, emp_id


def _add_claim(engine, cid, emp_id, *, status, receipt, amount="10.00") -> uuid.UUID:
    claim_id = uuid.uuid4()
    with Session(engine) as sess:
        sess.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        sess.add(
            Reimbursement(
                id=claim_id,
                company_id=cid,
                employee_id=emp_id,
                type=ReimbursementType.food,
                amount=Decimal(amount),
                expense_date=_day(3),
                description="d",
                file_object_id=receipt,
                status=status,
            )
        )
        sess.commit()
    return claim_id


def _add_receipt(engine, cid) -> uuid.UUID:
    file_id = uuid.uuid4()
    with Session(engine) as sess:
        sess.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        sess.add(
            FileObject(
                id=file_id,
                company_id=cid,
                file_name="r.pdf",
                file_type=PDF,
                file_size=1,
                storage_path=f"/nowhere/{file_id.hex}.pdf",
            )
        )
        sess.commit()
    return file_id


def _purge_mig(engine, cid: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
        for table in ("reimbursements", "file_objects", "employees"):
            conn.execute(text(f"DELETE FROM {table} WHERE company_id = :c"), {"c": cid})
        conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": cid})


def _status_labels(engine) -> set[str]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT unnest(enum_range(NULL::reimbursement_status))::text")
            ).fetchall()
        }


def test_R7_the_migration_round_trips_and_a_downgrade_turns_withdrawn_into_rejected() -> None:
    assert hasattr(ReimbursementStatus, "withdrawn"), "R7: the status enum needs 'withdrawn'"
    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    cid, emp_id = _orm_company_with_employee(engine)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        script = ScriptDirectory.from_config(cfg)
        assert len(script.get_heads()) == 1, "R7: there must be a single head"
        try:
            receipt = _add_receipt(engine, cid)
            claim_id = _add_claim(
                engine, cid, emp_id, status=ReimbursementStatus.withdrawn, receipt=receipt
            )
            command.downgrade(cfg, _previous_revision())
            assert "withdrawn" not in _status_labels(engine), "R7: downgrade must drop the value"
            names = {i["name"] for i in inspect(engine).get_indexes("reimbursements")}
            assert "uq_reimbursements_open_receipt" not in names, "R7: downgrade kept an index"
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.is_platform_admin', 'on', true)"))
                status = conn.execute(
                    text("SELECT status::text FROM reimbursements WHERE id = :i"), {"i": claim_id}
                ).scalar_one()
            assert status == "rejected", f"R7: withdrawn must become rejected, got {status}"

            command.upgrade(cfg, MIGRATION_REVISION)
            assert "withdrawn" in _status_labels(engine), "R7: upgrade must add the value"
            names = {i["name"] for i in inspect(engine).get_indexes("reimbursements")}
            assert {"uq_reimbursements_open_receipt", "uq_reimbursements_open_claim"} <= names
        finally:
            _purge_mig(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R3_the_migration_fails_loudly_on_two_open_claims_with_one_receipt() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    cid, emp_id = _orm_company_with_employee(engine)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, _previous_revision())
            receipt = _add_receipt(engine, cid)
            for amount in ("10.00", "11.00"):
                _add_claim(
                    engine,
                    cid,
                    emp_id,
                    status=ReimbursementStatus.pending,
                    receipt=receipt,
                    amount=amount,
                )
            with pytest.raises(RuntimeError) as caught:
                command.upgrade(cfg, MIGRATION_REVISION)
            message = str(caught.value).lower()
            assert "receipt" in message and "duplicate" in message, f"R3: unclear: {message}"
        finally:
            _purge_mig(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R3_the_migration_fails_loudly_on_duplicate_open_claims() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    cid, emp_id = _orm_company_with_employee(engine)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, _previous_revision())
            for _ in range(2):
                _add_claim(
                    engine,
                    cid,
                    emp_id,
                    status=ReimbursementStatus.approved,
                    receipt=None,
                    amount="10.00",
                )
            with pytest.raises(RuntimeError) as caught:
                command.upgrade(cfg, MIGRATION_REVISION)
            message = str(caught.value).lower()
            assert "duplicate" in message and "claim" in message, f"R3: unclear: {message}"
        finally:
            _purge_mig(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R1_the_migration_fails_loudly_on_a_receipt_that_points_at_no_file() -> None:
    assert settings.TEST_MIGRATION_URL is not None
    engine = create_engine(settings.TEST_MIGRATION_URL)
    cid, emp_id = _orm_company_with_employee(engine)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        cfg = _cfg()
        try:
            command.downgrade(cfg, _previous_revision())
            _add_claim(
                engine, cid, emp_id, status=ReimbursementStatus.pending, receipt=uuid.uuid4()
            )
            with pytest.raises(RuntimeError) as caught:
                command.upgrade(cfg, MIGRATION_REVISION)
            message = str(caught.value).lower()
            assert "receipt" in message and "file" in message, f"R1: unclear: {message}"
        finally:
            _purge_mig(engine, cid)
            command.upgrade(cfg, "head")
            engine.dispose()


def test_R10_every_rule_from_1_to_9_has_a_named_test() -> None:
    names = [n for n in globals() if n.startswith("test_R")]
    for rule in range(1, 10):
        assert any(n.startswith(f"test_R{rule}_") for n in names), f"R10: no test for rule {rule}"
    assert Path(__file__).name == "test_5_6_reimbursements.py"
