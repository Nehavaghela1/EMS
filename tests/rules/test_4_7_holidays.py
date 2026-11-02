"""Module 4, sub-feature 4.7: Holidays. One test per rule line (R1..R10).

Dates that a rule compares with today are computed from utcnow(); fixed dates
below are only stored or compared with other fixed dates.
"""

import threading
import uuid
from datetime import timedelta
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.db.session import get_db
from app.main import app as fastapi_app
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.platform.models import AuditLog
from tests.conftest import REPO_ROOT, TenantContext, _make_user_headers
from tests.integration.test_leaves import (
    _create_employee,
    _create_leave_type,
    _link_user_to_employee,
    _next_monday_through_friday,
)

HOLIDAYS = "/api/v1/holidays"
MIGRATION_REVISION = "c4d5e6f7a8b9"
PREVIOUS_REVISION = "a1b2c3d4e5f6"


def _owner_headers(db: Session, ctx: TenantContext) -> dict[str, str]:
    headers = _make_user_headers(db, ctx.company_id, UserRole.owner)
    db.commit()
    return headers


def _create(client: TestClient, headers: dict[str, str], **body: Any):
    payload: dict[str, Any] = {"name": "Founders Day", "date": "2031-03-03"}
    payload.update(body)
    return client.post(HOLIDAYS, headers=headers, json=payload)


def _audit_rows(db: Session, ctx: TenantContext, action: str) -> list[AuditLog]:
    bind_tenant_to_session(db, company_id=ctx.company_id, is_platform_admin=False)
    return (
        db.query(AuditLog)
        .filter(AuditLog.company_id == ctx.company_id, AuditLog.action == action)
        .all()
    )


def _department(client: TestClient, headers: dict[str, str], name: str) -> str:
    resp = client.post("/api/v1/departments", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _apply(client, headers, employee_id: str, leave_type_id: str, start, end):
    return client.post(
        "/api/v1/leaves",
        headers=headers,
        json={
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "reason": "Holiday rule test",
        },
    )


# ---------------------------------------------------------------- R1 roles


def test_R1_no_login_gets_401(client: TestClient) -> None:
    assert client.post(HOLIDAYS, json={"name": "X", "date": "2031-01-01"}).status_code == 401
    assert client.get(HOLIDAYS).status_code == 401
    assert client.delete(f"{HOLIDAYS}/{uuid.uuid4()}").status_code == 401
    assert client.post(f"{HOLIDAYS}/import-regional", json={}).status_code == 401


def test_R1_manager_and_employee_writes_get_403(client: TestClient, company_a: TenantContext):
    existing = _create(client, company_a.hr_headers)
    assert existing.status_code == 201, existing.text
    for who, headers in (
        ("manager", company_a.manager_headers),
        ("employee", company_a.employee_headers),
    ):
        post = _create(client, headers, date="2031-04-04")
        assert post.status_code == 403, (
            f"R1: {who} must not create a holiday, got {post.status_code}"
        )
        delete = client.delete(f"{HOLIDAYS}/{existing.json()['id']}", headers=headers)
        assert delete.status_code == 403, f"R1: {who} must not delete a holiday"
        imp = client.post(f"{HOLIDAYS}/import-regional", headers=headers, json={})
        assert imp.status_code == 403, f"R1: {who} must not import holidays"


def test_R1_owner_and_hr_admin_create_delete_and_import(
    client: TestClient, db: Session, company_a: TenantContext
):
    owner = _owner_headers(db, company_a)
    for headers, day in ((company_a.hr_headers, "2031-05-05"), (owner, "2031-05-06")):
        created = _create(client, headers, date=day)
        assert created.status_code == 201, created.text
        assert (
            client.delete(f"{HOLIDAYS}/{created.json()['id']}", headers=headers).status_code == 204
        )
        imp = client.post(
            f"{HOLIDAYS}/import-regional",
            headers=headers,
            json={"country": "IN", "state": "Gujarat", "year": 2027},
        )
        assert imp.status_code == 200, imp.text


def test_R1_every_user_lists_holidays_by_year(client: TestClient, company_a: TenantContext):
    assert _create(client, company_a.hr_headers, name="Y2031", date="2031-06-06").status_code == 201
    assert _create(client, company_a.hr_headers, name="Y2032", date="2032-06-06").status_code == 201
    for headers in (
        company_a.employee_headers,
        company_a.manager_headers,
        company_a.hr_headers,
    ):
        resp = client.get(f"{HOLIDAYS}?year=2031", headers=headers)
        assert resp.status_code == 200, resp.text
        assert [h["name"] for h in resp.json()] == ["Y2031"], "R1: list must filter by year"


# --------------------------------------------------------------- R2 input


def test_R2_name_is_trimmed_and_limited_to_150(client: TestClient, company_a: TenantContext):
    ok = _create(client, company_a.hr_headers, name="   Spaced Out   ", date="2031-07-07")
    assert ok.status_code == 201 and ok.json()["name"] == "Spaced Out", "R2: name not trimmed"
    longest = _create(client, company_a.hr_headers, name="x" * 150, date="2031-07-08")
    assert longest.status_code == 201, "R2: 150 characters must be accepted"
    for bad in ("", "    ", "x" * 151):
        resp = _create(client, company_a.hr_headers, name=bad, date="2031-07-09")
        assert resp.status_code == 422, f"R2: name {bad[:5]!r}/{len(bad)} must give 422"


def test_R2_date_must_be_valid_and_between_2000_and_2100(
    client: TestClient, company_a: TenantContext
):
    for bad in ("1999-12-31", "2101-01-01", "2031-02-30", "not-a-date"):
        resp = _create(client, company_a.hr_headers, date=bad)
        assert resp.status_code == 422, f"R2: date {bad} must give 422, got {resp.status_code}"
    for good in ("2000-01-01", "2100-12-31"):
        resp = _create(client, company_a.hr_headers, date=good)
        assert resp.status_code == 201, f"R2: boundary {good} must be accepted: {resp.text}"


def test_R2_unknown_fields_and_nulls_give_422(client: TestClient, company_a: TenantContext):
    extra = _create(client, company_a.hr_headers, color="red")
    assert extra.status_code == 422, "R2: unknown field must give 422"
    assert _create(client, company_a.hr_headers, name=None).status_code == 422
    assert _create(client, company_a.hr_headers, date=None).status_code == 422
    imp = client.post(
        f"{HOLIDAYS}/import-regional", headers=company_a.hr_headers, json={"bogus": 1}
    )
    assert imp.status_code == 422, "R2: unknown field on import must give 422"


def test_R2_department_must_exist_in_same_company(client: TestClient, company_a: TenantContext):
    dept = _department(client, company_a.hr_headers, f"Dept {uuid.uuid4().hex[:6]}")
    ok = _create(client, company_a.hr_headers, date="2031-08-08", applies_to_department_id=dept)
    assert ok.status_code == 201 and ok.json()["applies_to_department_id"] == dept
    missing = _create(
        client, company_a.hr_headers, date="2031-08-09", applies_to_department_id=str(uuid.uuid4())
    )
    assert missing.status_code == 404, f"R2: unknown department must give 404, got {missing.text}"


# ----------------------------------------------------------- R3 duplicates


def test_R3_same_date_twice_is_409_company_wide_and_per_department(
    client: TestClient, company_a: TenantContext
):
    assert _create(client, company_a.hr_headers, date="2031-09-09").status_code == 201
    again = _create(client, company_a.hr_headers, name="Other name", date="2031-09-09")
    assert again.status_code == 409, (
        f"R3: duplicate company-wide date must give 409, got {again.status_code}"
    )
    assert again.json()["error"]["code"] == "conflict"

    dept = _department(client, company_a.hr_headers, f"Dept {uuid.uuid4().hex[:6]}")
    assert (
        _create(
            client, company_a.hr_headers, date="2031-09-10", applies_to_department_id=dept
        ).status_code
        == 201
    )
    dup = _create(client, company_a.hr_headers, date="2031-09-10", applies_to_department_id=dept)
    assert dup.status_code == 409, "R3: duplicate department date must give 409"


def test_R3_company_wide_and_department_holiday_can_share_a_date(
    client: TestClient, company_a: TenantContext
):
    dept = _department(client, company_a.hr_headers, f"Dept {uuid.uuid4().hex[:6]}")
    assert _create(client, company_a.hr_headers, date="2031-10-10").status_code == 201
    both = _create(client, company_a.hr_headers, date="2031-10-10", applies_to_department_id=dept)
    assert both.status_code == 201, f"R3/R4: dept holiday on a company date allowed: {both.text}"


def test_R3_deleted_holiday_date_can_be_added_again(client: TestClient, company_a: TenantContext):
    first = _create(client, company_a.hr_headers, date="2031-11-11")
    assert first.status_code == 201
    assert (
        client.delete(f"{HOLIDAYS}/{first.json()['id']}", headers=company_a.hr_headers).status_code
        == 204
    )
    again = _create(client, company_a.hr_headers, date="2031-11-11")
    assert again.status_code == 201, f"R3: date of a deleted holiday must be reusable: {again.text}"


def _purge_race_holidays() -> None:
    """The race test commits for real (two sessions), so it removes its own holidays,
    otherwise they would block the migration round trip test below."""
    assert settings.TEST_MIGRATION_URL is not None
    owner = create_engine(settings.TEST_MIGRATION_URL)
    try:
        with owner.begin() as conn:
            conn.execute(text("ALTER TABLE holidays NO FORCE ROW LEVEL SECURITY"))
            conn.execute(
                text(
                    "DELETE FROM holidays WHERE company_id IN "
                    "(SELECT id FROM companies WHERE name = 'Holiday Race Co')"
                )
            )
            conn.execute(text("ALTER TABLE holidays FORCE ROW LEVEL SECURITY"))
    finally:
        owner.dispose()


def test_R3_two_simultaneous_requests_give_one_201_and_one_409() -> None:
    assert settings.TEST_DATABASE_URL is not None
    _purge_race_holidays()
    engine = create_engine(settings.TEST_DATABASE_URL, pool_size=5, max_overflow=2)
    try:
        with Session(engine) as setup:
            cid = uuid.uuid4()
            setup.add(
                Company(
                    id=cid,
                    name="Holiday Race Co",
                    code=f"HRC{uuid.uuid4().hex[:4].upper()}",
                    email=f"hrc-{uuid.uuid4().hex[:6]}@example.com",
                    status=CompanyStatus.active,
                    is_active=True,
                )
            )
            user = User(
                id=uuid.uuid4(),
                company_id=cid,
                email=f"hr-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password=hash_password("Test1234pass!"),
                role=UserRole.hr_admin,
                is_active=True,
            )
            setup.add(user)
            setup.commit()
            token = create_access_token(sub=str(user.id), company_id=str(cid), role="hr_admin")
        headers = {"Authorization": f"Bearer {token}"}

        def _get_test_db():
            session = Session(engine)
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _get_test_db
        barrier = threading.Barrier(2)
        results: list[int] = []

        def worker() -> None:
            local = TestClient(fastapi_app)
            try:
                barrier.wait()
                results.append(
                    local.post(
                        HOLIDAYS, headers=headers, json={"name": "Race", "date": "2031-12-12"}
                    ).status_code
                )
            except Exception:
                results.append(999)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results and 999 not in results, f"R3: race gave a 500: {results}"
        assert sorted(results) == [201, 409], f"R3: expected one 201 and one 409, got {results}"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        _purge_race_holidays()


# ------------------------------------------------- R4 / R5 / R6 leave days


def _leave_days(client, db, ctx: TenantContext, holidays: list[dict[str, Any]]) -> float:
    """Create an employee and a Monday to Friday leave; return total_days."""
    monday, friday = _next_monday_through_friday()
    owner = _owner_headers(db, ctx)
    for h in holidays:
        body = {
            "name": h["name"],
            "date": (monday + timedelta(days=h["offset"])).isoformat(),
            "is_optional": h.get("optional", False),
        }
        if "department" in h:
            body["applies_to_department_id"] = h["department"]
        assert client.post(HOLIDAYS, headers=ctx.hr_headers, json=body).status_code == 201
    employee = _create_employee(
        client,
        ctx.hr_headers,
        email=f"e-{uuid.uuid4().hex[:8]}@holidayco.com",
        **(
            {"department_id": holidays[0]["department"]}
            if holidays and "department" in holidays[0]
            else {}
        ),
    )
    leave_type = _create_leave_type(client, ctx.hr_headers, annual_allowance="30")
    resp = _apply(client, owner, employee["id"], leave_type["id"], monday, friday)
    assert resp.status_code == 201, resp.text
    return float(resp.json()["total_days"])


def test_R4_company_and_department_holiday_on_one_date_count_as_one_day_off(
    client: TestClient, db: Session, company_a: TenantContext
):
    dept = _department(client, company_a.hr_headers, f"Dept {uuid.uuid4().hex[:6]}")
    days = _leave_days(
        client,
        db,
        company_a,
        [
            {"name": "Dept day", "offset": 2, "department": dept},
            {"name": "Company day", "offset": 2},
        ],
    )
    assert days == 4.0, f"R4: two holidays on one date must remove one day only, got {days}"


def test_R5_mandatory_holiday_is_a_day_off_optional_is_not(
    client: TestClient, db: Session, company_a: TenantContext
):
    mandatory = _leave_days(client, db, company_a, [{"name": "Mandatory", "offset": 2}])
    assert mandatory == 4.0, f"R5: mandatory holiday must be excluded, got {mandatory}"


def test_R5_optional_holiday_is_not_a_day_off(
    client: TestClient, db: Session, company_a: TenantContext
):
    days = _leave_days(client, db, company_a, [{"name": "Optional", "offset": 2, "optional": True}])
    assert days == 5.0, f"R5: optional holiday must not remove a leave day, got {days}"


def test_R5_optional_holiday_is_listed_and_marked(client: TestClient, company_a: TenantContext):
    created = _create(client, company_a.hr_headers, date="2031-03-17", is_optional=True)
    assert created.status_code == 201 and created.json()["is_optional"] is True
    listed = client.get(f"{HOLIDAYS}?year=2031", headers=company_a.employee_headers).json()
    assert [h["is_optional"] for h in listed] == [True], "R5: optional flag must be listed"


def test_R5_calendar_shows_mandatory_holiday_but_not_optional(
    client: TestClient, db: Session, company_a: TenantContext
):
    employee = _create_employee(
        client, company_a.hr_headers, email=f"c-{uuid.uuid4().hex[:8]}@holidayco.com"
    )
    headers = _link_user_to_employee(db, company_a.company_id, employee["id"], UserRole.employee)
    monday, _ = _next_monday_through_friday()
    mandatory_day, optional_day = monday + timedelta(days=1), monday + timedelta(days=2)
    for day, optional in ((mandatory_day, False), (optional_day, True)):
        assert (
            client.post(
                HOLIDAYS,
                headers=company_a.hr_headers,
                json={"name": f"H{day.day}", "date": day.isoformat(), "is_optional": optional},
            ).status_code
            == 201
        )
    cal = client.get(
        f"/api/v1/attendance/calendar?month={monday.month}&year={monday.year}", headers=headers
    )
    assert cal.status_code == 200, cal.text
    by_date = {d["date"]: d for d in cal.json()["days"]}
    assert by_date[mandatory_day.isoformat()]["status"] == "holiday", "R5: mandatory not shown"
    assert by_date[optional_day.isoformat()]["status"] != "holiday", "R5: optional shown as day off"


def test_R6_adding_or_deleting_a_holiday_never_changes_an_approved_leave(
    client: TestClient, db: Session, company_a: TenantContext
):
    monday, friday = _next_monday_through_friday()
    owner = _owner_headers(db, company_a)
    employee = _create_employee(
        client, company_a.hr_headers, email=f"s-{uuid.uuid4().hex[:8]}@holidayco.com"
    )
    leave_type = _create_leave_type(client, company_a.hr_headers, annual_allowance="30")
    leave = _apply(client, owner, employee["id"], leave_type["id"], monday, friday).json()
    assert leave["status"] == "approved" and float(leave["total_days"]) == 5.0

    added = _create(client, company_a.hr_headers, date=(monday + timedelta(days=1)).isoformat())
    assert added.status_code == 201
    after_add = client.get(f"/api/v1/leaves/{leave['id']}", headers=company_a.hr_headers).json()
    assert float(after_add["total_days"]) == 5.0, "R6: adding a holiday changed an approved leave"

    assert (
        client.delete(f"{HOLIDAYS}/{added.json()['id']}", headers=company_a.hr_headers).status_code
        == 204
    )
    after_delete = client.get(f"/api/v1/leaves/{leave['id']}", headers=company_a.hr_headers).json()
    assert float(after_delete["total_days"]) == 5.0, (
        "R6: deleting a holiday changed an approved leave"
    )


# -------------------------------------------------------------- R7 import


def test_R7_import_checks_country_state_and_year(client: TestClient, company_a: TenantContext):
    url = f"{HOLIDAYS}/import-regional"
    for body in (
        {"country": "ZZ", "state": "Gujarat", "year": 2027},
        {"country": "IN", "state": "Atlantis", "year": 2027},
        {"country": "IN", "state": "Gujarat", "year": 1999},
        {"country": "IN", "state": "Gujarat", "year": 2101},
        {"country": "IN", "state": "Texas", "year": 2027},
    ):
        resp = client.post(url, headers=company_a.hr_headers, json=body)
        assert resp.status_code == 422, f"R7: {body} must give 422, got {resp.status_code}"
        preview = client.get(
            f"{HOLIDAYS}/regional-preview?country={body['country']}&state={body['state']}&year={body['year']}",
            headers=company_a.hr_headers,
        )
        assert preview.status_code == 422, f"R7: preview of {body} must give 422"


def test_R7_import_skips_duplicates_and_preview_matches(
    client: TestClient, company_a: TenantContext
):
    preview = client.get(
        f"{HOLIDAYS}/regional-preview?country=IN&state=Gujarat&year=2027",
        headers=company_a.hr_headers,
    )
    assert preview.status_code == 200 and len(preview.json()) > 0
    pre_existing = _create(
        client, company_a.hr_headers, name="Mine", date=preview.json()[0]["date"]
    )
    assert pre_existing.status_code == 201
    first = client.post(
        f"{HOLIDAYS}/import-regional",
        headers=company_a.hr_headers,
        json={"country": "IN", "state": "Gujarat", "year": 2027},
    )
    assert first.status_code == 200, first.text
    assert first.json()["imported_count"] == len(preview.json()) - 1, "R7: duplicate not skipped"
    second = client.post(
        f"{HOLIDAYS}/import-regional",
        headers=company_a.hr_headers,
        json={"country": "IN", "state": "Gujarat", "year": 2027},
    )
    assert second.json()["imported_count"] == 0, "R7: second import must add nothing"


def test_R7_import_route_says_hr_must_confirm_the_lists(client: TestClient):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"]["/api/v1/holidays/import-regional"]["post"]
    text_blob = (operation.get("description", "") + operation.get("summary", "")).lower()
    assert "official notification" in text_blob, "R7: route must tell HR to confirm the lists"


# --------------------------------------------------------------- R8 audit


def test_R8_create_delete_and_import_each_write_one_audit_row(
    client: TestClient, db: Session, company_a: TenantContext
):
    created = _create(client, company_a.hr_headers, name="Secret Name Day", date="2031-02-02")
    holiday_id = uuid.UUID(created.json()["id"])
    rows = _audit_rows(db, company_a, "HOLIDAY_CREATED")
    assert len(rows) == 1 and rows[0].entity_id == holiday_id, "R8: HOLIDAY_CREATED missing"
    assert rows[0].details["date"] == "2031-02-02"
    assert "Secret Name Day" not in str(rows[0].details), "R8: holiday name leaked into audit"

    assert (
        client.delete(f"{HOLIDAYS}/{holiday_id}", headers=company_a.hr_headers).status_code == 204
    )
    deleted = _audit_rows(db, company_a, "HOLIDAY_DELETED")
    assert len(deleted) == 1 and deleted[0].entity_id == holiday_id, "R8: HOLIDAY_DELETED missing"

    imp = client.post(
        f"{HOLIDAYS}/import-regional",
        headers=company_a.hr_headers,
        json={"country": "IN", "state": "Gujarat", "year": 2028},
    )
    imported = _audit_rows(db, company_a, "HOLIDAYS_IMPORTED")
    assert len(imported) == 1, "R8: HOLIDAYS_IMPORTED missing"
    assert imported[0].details["count"] == imp.json()["imported_count"]
    assert imported[0].details["year"] == 2028


def test_R8_failed_create_writes_no_audit_row(
    client: TestClient, db: Session, company_a: TenantContext
):
    assert _create(client, company_a.hr_headers, date="2031-02-03").status_code == 201
    assert _create(client, company_a.hr_headers, date="2031-02-03").status_code == 409
    assert len(_audit_rows(db, company_a, "HOLIDAY_CREATED")) == 1


# ---------------------------------------------------------- R9 rate limits


@pytest.fixture
def limits_on():
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


def test_R9_create_is_limited_to_30_per_minute(client, company_a, limits_on):
    codes = [
        _create(client, company_a.hr_headers, date=f"2040-01-{i:02d}").status_code
        for i in range(1, 32)
    ]
    assert codes[:30] == [201] * 30 and codes[30] == 429, f"R9: create limit wrong: {codes}"


def test_R9_delete_is_limited_to_30_per_minute(client, company_a):
    ids = [
        _create(client, company_a.hr_headers, date=f"2041-01-{i:02d}").json()["id"]
        for i in range(1, 32)
    ]
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [
            client.delete(f"{HOLIDAYS}/{i}", headers=company_a.hr_headers).status_code for i in ids
        ]
    finally:
        limiter.reset()
        limiter.enabled = False
    assert codes[:30] == [204] * 30 and codes[30] == 429, f"R9: delete limit wrong: {codes}"


def test_R9_reads_are_limited_to_60_per_minute(client, company_a, limits_on):
    for path in ("", "/regions", "/regional-preview?country=IN&state=Gujarat&year=2027"):
        limiter.reset()
        codes = [
            client.get(f"{HOLIDAYS}{path}", headers=company_a.employee_headers).status_code
            for _ in range(61)
        ]
        assert codes[:60] == [200] * 60 and codes[60] == 429, f"R9: read limit wrong on {path!r}"


def test_R9_import_is_limited_to_5_per_minute(client, company_a, limits_on):
    codes = [
        client.post(
            f"{HOLIDAYS}/import-regional",
            headers=company_a.hr_headers,
            json={"country": "IN", "state": "Gujarat", "year": 2027},
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [200] * 5 and codes[5] == 429, f"R9: import limit wrong: {codes}"


# --------------------------------------------------------- R10 other company


def test_R10_other_company_holiday_and_department_give_the_same_404(
    client: TestClient, company_a: TenantContext, company_b: TenantContext
):
    foreign = _create(client, company_b.hr_headers, date="2031-01-21")
    assert foreign.status_code == 201
    missing_id = str(uuid.uuid4())
    foreign_delete = client.delete(
        f"{HOLIDAYS}/{foreign.json()['id']}", headers=company_a.hr_headers
    )
    missing_delete = client.delete(f"{HOLIDAYS}/{missing_id}", headers=company_a.hr_headers)
    assert foreign_delete.status_code == 404 == missing_delete.status_code
    assert foreign_delete.json()["error"]["message"] == missing_delete.json()["error"]["message"]

    foreign_dept = _department(client, company_b.hr_headers, f"B {uuid.uuid4().hex[:6]}")
    via_foreign = _create(
        client, company_a.hr_headers, date="2031-01-22", applies_to_department_id=foreign_dept
    )
    via_missing = _create(
        client, company_a.hr_headers, date="2031-01-23", applies_to_department_id=missing_id
    )
    assert via_foreign.status_code == 404 == via_missing.status_code
    assert via_foreign.json()["error"]["message"] == via_missing.json()["error"]["message"]
    listed = client.get(f"{HOLIDAYS}?year=2031", headers=company_a.hr_headers).json()
    assert listed == [], "R10: another company's holiday leaked into the list"
    still_there = client.get(f"{HOLIDAYS}?year=2031", headers=company_b.hr_headers).json()
    assert len(still_there) == 1, "R10: foreign delete must not remove the holiday"


# ------------------------------------------------------------ R3 migration


def test_R3_migration_partial_unique_index_round_trip() -> None:
    """After the migration a deleted holiday and an active one may share a date;
    the downgrade refuses with a clear message when that data exists."""
    assert settings.TEST_MIGRATION_URL is not None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "ALEMBIC_DATABASE_URL", settings.TEST_MIGRATION_URL)
        engine = create_engine(settings.TEST_MIGRATION_URL)
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        # Re-apply the migration file as it is now, so this test always checks the file on disk.
        command.downgrade(cfg, PREVIOUS_REVISION)
        command.upgrade(cfg, MIGRATION_REVISION)
        company_id = uuid.uuid4()
        code = f"MH{company_id.hex[:10].upper()}"
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO companies (id, name, code, email, status, country, currency,"
                        " last_employee_seq, created_at, updated_at) VALUES (:i, 'Mig Holiday Co',"
                        " :c, :e, 'active', 'IN', 'INR', 0, NOW(), NOW())"
                    ),
                    {"i": company_id, "c": code, "e": f"{code.lower()}@test.test"},
                )
            indexes = {i["name"] for i in inspect(engine).get_indexes("holidays")}
            assert "uq_holidays_company_date_department" in indexes, "R3: partial index missing"

            insert = (
                "INSERT INTO holidays (id, company_id, name, date, is_optional, deleted_at,"
                " created_at, updated_at) VALUES (gen_random_uuid(), :c, :n, '2031-04-04', false,"
                " {deleted}, NOW(), NOW())"
            )

            def _run(deleted: str, name: str) -> None:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE holidays NO FORCE ROW LEVEL SECURITY"))
                    conn.execute(text(insert.format(deleted=deleted)), {"c": company_id, "n": name})
                    conn.execute(text("ALTER TABLE holidays FORCE ROW LEVEL SECURITY"))

            _run("NOW()", "old")
            _run("NULL", "new")  # allowed only because the index is partial
            with pytest.raises(RuntimeError) as exc:
                command.downgrade(cfg, PREVIOUS_REVISION)
            assert "holiday" in str(exc.value).lower() and "duplicate" in str(exc.value).lower()

            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE holidays NO FORCE ROW LEVEL SECURITY"))
                conn.execute(text("DELETE FROM holidays WHERE company_id = :c"), {"c": company_id})
                conn.execute(text("ALTER TABLE holidays FORCE ROW LEVEL SECURITY"))
            command.downgrade(cfg, PREVIOUS_REVISION)
            names = {c["name"] for c in inspect(engine).get_unique_constraints("holidays")}
            assert "uq_holidays_company_id_date_department_id" in names
            command.upgrade(cfg, MIGRATION_REVISION)
            indexes = {i["name"] for i in inspect(engine).get_indexes("holidays")}
            assert "uq_holidays_company_date_department" in indexes
        finally:
            try:
                command.upgrade(cfg, "head")
            finally:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE holidays NO FORCE ROW LEVEL SECURITY"))
                    conn.execute(
                        text("DELETE FROM holidays WHERE company_id = :c"), {"c": company_id}
                    )
                    conn.execute(text("ALTER TABLE holidays FORCE ROW LEVEL SECURITY"))
                    conn.execute(text("DELETE FROM companies WHERE id = :c"), {"c": company_id})
                engine.dispose()
