import uuid
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType, InvitationStatus
from app.modules.identity.models import Company, CompanyStatus, User, UserRole
from app.modules.performance.models import (
    CycleStatus,
    PerformanceCycle,
    PerformanceSummary,
)


@pytest.fixture
def hr_summary_setup(db):
    db.expire_on_commit = False
    cid = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    company = Company(
        id=cid,
        name=f"Comp_{uuid.uuid4().hex[:6]}",
        code=f"C{uuid.uuid4().hex[:6].upper()}",
        email=f"co_{uuid.uuid4().hex[:6]}@example.com",
        status=CompanyStatus.active,
    )
    db.add(company)
    db.flush()

    hr_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"hr_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.hr_admin,
        is_active=True,
    )
    owner_user = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"owner_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.owner,
        is_active=True,
    )
    db.add_all([hr_user, owner_user])
    db.flush()

    emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=None,
        employee_code=f"E{uuid.uuid4().hex[:6]}",
        first_name="John",
        last_name="Doe",
        email=f"emp_{uuid.uuid4().hex[:6]}@example.com",
        hire_date="2026-01-01",
        employment_type=EmploymentType.full_time,
        invitation_status=InvitationStatus.activated,
        resignation_status="none",
        is_active=True,
    )
    db.add(emp)
    db.flush()

    cycle = PerformanceCycle(
        id=uuid.uuid4(),
        company_id=cid,
        name="Annual 2026",
        cycle_type="annual",
        start_date="2026-01-01",
        end_date="2026-12-31",
        status=CycleStatus.active,
    )
    db.add(cycle)
    db.flush()

    summary = PerformanceSummary(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp.id,
        cycle_id=cycle.id,
        final_rating=Decimal("4.5"),
        overall_comments="Great performance",
        salary_revision_recommended=True,
        recommended_increment_percent=Decimal("10.00"),
        reviewed_by=hr_user.id,
        finalized_at="2026-11-20T10:00:00Z",
    )
    db.add(summary)
    db.commit()

    hr_token = create_access_token(
        sub=str(hr_user.id), company_id=str(cid), role=hr_user.role.value
    )
    owner_token = create_access_token(
        sub=str(owner_user.id), company_id=str(cid), role=owner_user.role.value
    )

    return {
        "hr_headers": {"Authorization": f"Bearer {hr_token}"},
        "owner_headers": {"Authorization": f"Bearer {owner_token}"},
        "cycle_id": str(cycle.id),
        "employee_id": str(emp.id),
        "employee_name": "John Doe",
    }


def test_list_performance_summaries_hr_and_owner(client, hr_summary_setup):
    # HR Admin call
    resp = client.get(
        f"/api/v1/performance/summaries?cycle_id={hr_summary_setup['cycle_id']}",
        headers=hr_summary_setup["hr_headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["employee_name"] == "John Doe"
    assert data["items"][0]["final_rating"] == "4.5"
    assert data["items"][0]["salary_revision_recommended"] is True

    # Owner call
    resp_owner = client.get(
        f"/api/v1/performance/summaries?cycle_id={hr_summary_setup['cycle_id']}",
        headers=hr_summary_setup["owner_headers"],
    )
    assert resp_owner.status_code == 200, resp_owner.text
    assert resp_owner.json()["total"] == 1
