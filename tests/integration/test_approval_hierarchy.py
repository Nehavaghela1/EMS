import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.modules.hr.models import Employee
from app.modules.identity.models import User, UserRole
from app.modules.performance.models import PerformancePIP
from tests.conftest import TenantContext
from tests.integration.test_employees import _create_employee


def _link_user_to_employee(
    db: Session,
    company_id: uuid.UUID,
    employee_id: str,
    role: UserRole,
    is_active: bool = True,
) -> dict[str, str]:
    user = User(
        company_id=company_id,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    employee = db.get(Employee, uuid.UUID(employee_id))
    assert employee is not None
    employee.user_id = user.id
    if not is_active:
        employee.is_active = False
    db.commit()
    token = create_access_token(sub=str(user.id), company_id=str(company_id), role=role.value)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Helper: Setup Reporting Hierarchy (Employee -> Direct Manager -> Senior Manager)
# =============================================================================
def _setup_hierarchy(client: TestClient, db: Session, company: TenantContext):
    # 1. Senior Manager (reports to nobody)
    senior = _create_employee(
        client, company.hr_headers, email=f"senior-{uuid.uuid4().hex[:6]}@example.com"
    )
    senior_headers = _link_user_to_employee(db, company.company_id, senior["id"], UserRole.manager)

    # 2. Direct Manager (reports to Senior Manager)
    direct = _create_employee(
        client,
        company.hr_headers,
        email=f"direct-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=senior["id"],
    )
    direct_headers = _link_user_to_employee(db, company.company_id, direct["id"], UserRole.manager)

    # 3. Employee (reports to Direct Manager)
    emp = _create_employee(
        client,
        company.hr_headers,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=direct["id"],
    )
    emp_headers = _link_user_to_employee(db, company.company_id, emp["id"], UserRole.employee)

    # 4. Peer Manager (reports to nobody, does NOT manage emp)
    other_mgr = _create_employee(
        client, company.hr_headers, email=f"otherm-{uuid.uuid4().hex[:6]}@example.com"
    )
    other_mgr_headers = _link_user_to_employee(
        db, company.company_id, other_mgr["id"], UserRole.manager
    )

    return {
        "senior": senior,
        "senior_headers": senior_headers,
        "direct": direct,
        "direct_headers": direct_headers,
        "emp": emp,
        "emp_headers": emp_headers,
        "other_mgr": other_mgr,
        "other_mgr_headers": other_mgr_headers,
    }


# =============================================================================
# 1. LEAVE APPROVAL: PUT /api/v1/leaves/{leave_id}
# =============================================================================
def _create_pending_leave(client: TestClient, company: TenantContext, emp_headers: dict) -> str:
    lt_res = client.post(
        "/api/v1/leave-types",
        headers=company.hr_headers,
        json={
            "name": f"LT-{uuid.uuid4().hex[:4]}",
            "code": f"lt_{uuid.uuid4().hex[:4]}",
            "annual_allowance": "15",
        },
    )
    assert lt_res.status_code == 201
    lt_id = lt_res.json()["id"]

    res = client.post(
        "/api/v1/leaves",
        headers=emp_headers,
        json={
            "leave_type_id": lt_id,
            "start_date": "2030-01-10",
            "end_date": "2030-01-12",
            "reason": "Test leave",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_leave_approval_a_direct_manager_approves(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) Leave: direct reporting manager approves -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["direct_headers"], json={"status": "approved"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"


def test_leave_approval_b_non_reporting_manager_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) Leave: non-reporting manager approves -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["other_mgr_headers"], json={"status": "approved"}
    )
    assert res.status_code == 403, res.text


def test_leave_approval_c_employee_self_approval_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) Leave: employee approves own leave -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["emp_headers"], json={"status": "approved"}
    )
    assert res.status_code == 403, res.text


def test_leave_approval_d_hr_admin_own_company_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) Leave: hr_admin approves in own company -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=company_a.hr_headers, json={"status": "approved"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"


def test_leave_approval_e_cross_company_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """e) Leave: cross-company manager or hr_admin -> 403 or 404"""
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=company_b.hr_headers, json={"status": "approved"}
    )
    assert res.status_code in (403, 404), res.text


def test_leave_approval_f_second_approval_conflict(
    client: TestClient, db: Session, company_a: TenantContext
):
    """f) Leave: approving already approved leave -> 409 or clear error"""
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    first = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["direct_headers"], json={"status": "approved"}
    )
    assert first.status_code == 200

    second = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["direct_headers"], json={"status": "approved"}
    )
    assert second.status_code in (409, 400), second.text


def test_leave_approval_g_old_manager_revoked_after_hierarchy_change(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) Leave: after HR changes reporting manager, old manager can no longer approve"""
    h = _setup_hierarchy(client, db, company_a)

    # Change reporting manager to other_mgr
    update_res = client.put(
        f"/api/v1/employees/{h['emp']['id']}",
        headers=company_a.hr_headers,
        json={"reporting_manager_id": h["other_mgr"]["id"]},
    )
    assert update_res.status_code == 200

    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    old_res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["direct_headers"], json={"status": "approved"}
    )
    assert old_res.status_code == 403, old_res.text

    new_res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["other_mgr_headers"], json={"status": "approved"}
    )
    assert new_res.status_code == 200, new_res.text


def test_leave_approval_h_senior_in_chain_allowed_or_report(
    client: TestClient, db: Session, company_a: TenantContext
):
    """h) Leave: senior in reporting chain (manager's manager) approves ->
    product owner expected allowed
    """
    h = _setup_hierarchy(client, db, company_a)
    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["senior_headers"], json={"status": "approved"}
    )
    assert res.status_code == 200, f"Senior denied: {res.status_code} {res.text}"


def test_leave_approval_j_inactive_manager_denied(
    client: TestClient, db: Session, company_a: TenantContext
):
    """j) Leave: terminated/inactive manager -> 401 or 403"""
    h = _setup_hierarchy(client, db, company_a)
    # Deactivate direct manager
    direct_emp = db.get(Employee, uuid.UUID(h["direct"]["id"]))
    assert direct_emp and direct_emp.user_id
    user = db.get(User, direct_emp.user_id)
    assert user
    user.is_active = False
    direct_emp.is_active = False
    db.commit()

    leave_id = _create_pending_leave(client, company_a, h["emp_headers"])

    res = client.put(
        f"/api/v1/leaves/{leave_id}", headers=h["direct_headers"], json={"status": "approved"}
    )
    assert res.status_code in (401, 403), res.text


# =============================================================================
# 2. ATTENDANCE REGULARIZATION: PUT /api/v1/attendance/regularizations/{id}/approve
# =============================================================================
def _create_pending_regularization(client: TestClient, emp_headers: dict) -> str:
    checkin = client.post("/api/v1/attendance/check-in", headers=emp_headers)
    assert checkin.status_code == 201, checkin.text
    att_id = checkin.json()["id"]

    reg = client.post(
        f"/api/v1/attendance/{att_id}/regularize",
        headers=emp_headers,
        json={"reason": "Forgot check-out"},
    )
    assert reg.status_code == 200, reg.text
    return reg.json()["id"]


def test_regularization_approval_a_direct_manager_approves(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) Regularization: direct manager approves -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["direct_headers"],
        json={"status": "approved"},
    )
    assert res.status_code == 200, res.text


def test_regularization_approval_b_non_reporting_manager_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) Regularization: non-reporting manager approves -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["other_mgr_headers"],
        json={"status": "approved"},
    )
    assert res.status_code == 403, res.text


def test_regularization_approval_c_employee_self_approval_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) Regularization: employee self approval -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["emp_headers"],
        json={"status": "approved"},
    )
    assert res.status_code == 403, res.text


def test_regularization_approval_d_hr_admin_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) Regularization: hr_admin in own company -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=company_a.hr_headers,
        json={"status": "approved"},
    )
    assert res.status_code == 200, res.text


def test_regularization_approval_e_cross_company_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """e) Regularization: cross-company approval -> 403 or 404"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=company_b.hr_headers,
        json={"status": "approved"},
    )
    assert res.status_code in (403, 404), res.text


def test_regularization_approval_f_second_approval_conflict(
    client: TestClient, db: Session, company_a: TenantContext
):
    """f) Regularization: approving already approved item -> 409 or clear error"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    first = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["direct_headers"],
        json={"status": "approved"},
    )
    assert first.status_code == 200

    second = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["direct_headers"],
        json={"status": "approved"},
    )
    assert second.status_code in (409, 400), second.text


def test_regularization_approval_g_old_manager_revoked(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) Regularization: after HR changes manager, old manager cannot approve"""
    h = _setup_hierarchy(client, db, company_a)

    client.put(
        f"/api/v1/employees/{h['emp']['id']}",
        headers=company_a.hr_headers,
        json={"reporting_manager_id": h["other_mgr"]["id"]},
    )

    reg_id = _create_pending_regularization(client, h["emp_headers"])

    old_res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["direct_headers"],
        json={"status": "approved"},
    )
    assert old_res.status_code == 403, old_res.text


def test_regularization_approval_h_senior_in_chain_allowed_or_report(
    client: TestClient, db: Session, company_a: TenantContext
):
    """h) Regularization: senior in reporting chain approves -> product owner expected allowed"""
    h = _setup_hierarchy(client, db, company_a)
    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["senior_headers"],
        json={"status": "approved"},
    )
    assert res.status_code == 200, f"Senior denied: {res.status_code} {res.text}"


def test_regularization_approval_j_inactive_manager_denied(
    client: TestClient, db: Session, company_a: TenantContext
):
    """j) Regularization: inactive manager denied -> 401 or 403"""
    h = _setup_hierarchy(client, db, company_a)
    direct_emp = db.get(Employee, uuid.UUID(h["direct"]["id"]))
    assert direct_emp and direct_emp.user_id
    user = db.get(User, direct_emp.user_id)
    assert user
    user.is_active = False
    direct_emp.is_active = False
    db.commit()

    reg_id = _create_pending_regularization(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/attendance/regularizations/{reg_id}/approve",
        headers=h["direct_headers"],
        json={"status": "approved"},
    )
    assert res.status_code in (401, 403), res.text


# =============================================================================
# 3. RESIGNATION APPROVAL: PUT /api/v1/employees/{employee_id}/resignation/approve
# =============================================================================
def _submit_resignation(client: TestClient, emp_id: str, emp_headers: dict) -> None:
    res = client.post(
        f"/api/v1/employees/{emp_id}/resignation",
        headers=emp_headers,
        json={
            "resignation_date": "2026-09-01",
            "last_working_date": "2026-10-01",
            "reason": "Moving on",
        },
    )
    assert res.status_code == 200, res.text


def test_resignation_approval_a_direct_manager_approves(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) Resignation: direct manager approves -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert res.status_code == 200, res.text


def test_resignation_approval_b_non_reporting_manager_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) Resignation: non-reporting manager approves -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["other_mgr_headers"],
        json={"approved": True},
    )
    assert res.status_code == 403, res.text


def test_resignation_approval_c_employee_self_approval_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) Resignation: employee self approval -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["emp_headers"],
        json={"approved": True},
    )
    assert res.status_code == 403, res.text


def test_resignation_approval_d_hr_admin_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) Resignation: hr_admin in own company -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=company_a.hr_headers,
        json={"approved": True},
    )
    assert res.status_code == 200, res.text


def test_resignation_approval_e_cross_company_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """e) Resignation: cross-company approval -> 403 or 404"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=company_b.hr_headers,
        json={"approved": True},
    )
    assert res.status_code in (403, 404), res.text


def test_resignation_approval_f_second_approval_conflict(
    client: TestClient, db: Session, company_a: TenantContext
):
    """f) Resignation: approving already approved resignation -> 409 or clear error"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    first = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert first.status_code == 200

    second = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert second.status_code in (409, 400), second.text


def test_resignation_approval_g_old_manager_revoked(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) Resignation: after HR changes manager, old manager cannot approve"""
    h = _setup_hierarchy(client, db, company_a)

    client.put(
        f"/api/v1/employees/{h['emp']['id']}",
        headers=company_a.hr_headers,
        json={"reporting_manager_id": h["other_mgr"]["id"]},
    )

    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    old_res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert old_res.status_code == 403, old_res.text


def test_resignation_approval_h_senior_in_chain_allowed_or_report(
    client: TestClient, db: Session, company_a: TenantContext
):
    """h) Resignation: senior in chain approves -> product owner expected allowed"""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["senior_headers"],
        json={"approved": True},
    )
    assert res.status_code == 200, f"Senior denied: {res.status_code} {res.text}"


def test_resignation_approval_j_inactive_manager_denied(
    client: TestClient, db: Session, company_a: TenantContext
):
    """j) Resignation: inactive manager denied -> 401 or 403"""
    h = _setup_hierarchy(client, db, company_a)
    direct_emp = db.get(Employee, uuid.UUID(h["direct"]["id"]))
    assert direct_emp and direct_emp.user_id
    user = db.get(User, direct_emp.user_id)
    assert user
    user.is_active = False
    direct_emp.is_active = False
    db.commit()

    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    res = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert res.status_code in (401, 403), res.text


def test_resignation_approval_dept_head_own_resignation_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """1. Department head who is resigning tries to approve own resignation -> 403."""
    dept_res = client.post(
        "/api/v1/departments",
        json={"name": f"Dept-{uuid.uuid4().hex[:6]}", "description": "Dept Head test"},
        headers=company_a.hr_headers,
    )
    assert dept_res.status_code == 201
    dept_id = dept_res.json()["id"]

    head_emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"head-{uuid.uuid4().hex[:6]}@example.com",
        department_id=dept_id,
    )
    client.put(
        f"/api/v1/departments/{dept_id}",
        json={"head_employee_id": head_emp["id"]},
        headers=company_a.hr_headers,
    )
    head_headers = _link_user_to_employee(
        db, company_a.company_id, head_emp["id"], UserRole.manager
    )

    _submit_resignation(client, head_emp["id"], head_headers)

    res = client.put(
        f"/api/v1/employees/{head_emp['id']}/resignation/approve",
        headers=head_headers,
        json={"approved": True},
    )
    assert res.status_code == 403, res.text
    assert "Self-approval is forbidden" in res.text


def test_resignation_approval_hr_admin_own_resignation_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """2. An hr_admin approving their own resignation -> 403."""
    hr_emp = _create_employee(
        client, company_a.hr_headers, email=f"hr-{uuid.uuid4().hex[:6]}@example.com"
    )
    hr_headers = _link_user_to_employee(db, company_a.company_id, hr_emp["id"], UserRole.hr_admin)

    _submit_resignation(client, hr_emp["id"], hr_headers)

    res = client.put(
        f"/api/v1/employees/{hr_emp['id']}/resignation/approve",
        headers=hr_headers,
        json={"approved": True},
    )
    assert res.status_code == 403, res.text
    assert "Self-approval is forbidden" in res.text


def test_resignation_approval_super_admin_or_owner_own_resignation_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """3. An owner or super_admin approving their own resignation -> allowed."""
    sa_emp = _create_employee(
        client, company_a.hr_headers, email=f"sa-{uuid.uuid4().hex[:6]}@example.com"
    )
    sa_headers = _link_user_to_employee(
        db, company_a.company_id, sa_emp["id"], UserRole.super_admin
    )

    _submit_resignation(client, sa_emp["id"], sa_headers)

    res = client.put(
        f"/api/v1/employees/{sa_emp['id']}/resignation/approve",
        headers=sa_headers,
        json={"approved": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["resignation_status"] == "approved"


def test_resignation_approval_hr_admin_amends_approved_resignation(
    client: TestClient, db: Session, company_a: TenantContext
):
    """hr_admin amends an approved resignation and gets 200."""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    first = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True, "notice_recovery_days": 10},
    )
    assert first.status_code == 200, first.text
    assert first.json()["resignation_status"] == "approved"

    amend = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=company_a.hr_headers,
        json={"approved": True, "notice_waived": True, "notice_recovery_days": 0},
    )
    assert amend.status_code == 200, amend.text
    assert amend.json()["resignation_status"] == "approved"
    assert amend.json()["notice_waived"] is True
    assert amend.json()["notice_recovery_days"] == 0


def test_resignation_approval_reporting_manager_amend_approved_resignation_gets_409(
    client: TestClient, db: Session, company_a: TenantContext
):
    """Reporting manager tries to amend an approved resignation and gets 409."""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    first = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert first.status_code == 200, first.text

    second = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True, "notice_waived": True},
    )
    assert second.status_code == 409, second.text


def test_resignation_approval_unauthorized_manager_on_already_approved_gets_403(
    client: TestClient, db: Session, company_a: TenantContext
):
    """An unauthorized manager gets 403, not 409."""
    h = _setup_hierarchy(client, db, company_a)
    _submit_resignation(client, h["emp"]["id"], h["emp_headers"])

    approved = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["direct_headers"],
        json={"approved": True},
    )
    assert approved.status_code == 200, approved.text

    unauthorized = client.put(
        f"/api/v1/employees/{h['emp']['id']}/resignation/approve",
        headers=h["other_mgr_headers"],
        json={"approved": True},
    )
    assert unauthorized.status_code == 403, unauthorized.text


# =============================================================================
# 4. REIMBURSEMENT APPROVAL: PUT /api/v1/payroll/reimbursements/{id}
# =============================================================================
def _create_pending_reimbursement(client: TestClient, emp_headers: dict) -> str:
    res = client.post(
        "/api/v1/payroll/reimbursements",
        headers=emp_headers,
        json={
            "type": "travel",
            "amount": "1200.00",
            "expense_date": "2026-06-01",
            "description": "Travel expense",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_reimbursement_approval_a_direct_manager_approves(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) Reimbursement: direct manager approves -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["direct_headers"],
        json={"action": "approve"},
    )
    assert res.status_code == 200, res.text


def test_reimbursement_approval_b_non_reporting_manager_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) Reimbursement: non-reporting manager approves -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["other_mgr_headers"],
        json={"action": "approve"},
    )
    assert res.status_code == 403, res.text


def test_reimbursement_approval_c_employee_self_approval_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) Reimbursement: employee self approval -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["emp_headers"],
        json={"action": "approve"},
    )
    assert res.status_code == 403, res.text


def test_reimbursement_approval_d_hr_admin_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) Reimbursement: hr_admin in own company -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=company_a.hr_headers,
        json={"action": "approve"},
    )
    assert res.status_code == 200, res.text


def test_reimbursement_approval_e_cross_company_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """e) Reimbursement: cross-company approval -> 403 or 404"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=company_b.hr_headers,
        json={"action": "approve"},
    )
    assert res.status_code in (403, 404), res.text


def test_reimbursement_approval_f_second_approval_conflict(
    client: TestClient, db: Session, company_a: TenantContext
):
    """f) Reimbursement: approving already approved claim -> 409 or clear error"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    first = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["direct_headers"],
        json={"action": "approve"},
    )
    assert first.status_code == 200

    second = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["direct_headers"],
        json={"action": "approve"},
    )
    assert second.status_code in (409, 400), second.text


def test_reimbursement_approval_g_old_manager_revoked(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) Reimbursement: after HR changes manager, old manager cannot approve"""
    h = _setup_hierarchy(client, db, company_a)

    client.put(
        f"/api/v1/employees/{h['emp']['id']}",
        headers=company_a.hr_headers,
        json={"reporting_manager_id": h["other_mgr"]["id"]},
    )

    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    old_res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["direct_headers"],
        json={"action": "approve"},
    )
    assert old_res.status_code == 403, old_res.text


def test_reimbursement_approval_h_senior_in_chain_allowed_or_report(
    client: TestClient, db: Session, company_a: TenantContext
):
    """h) Reimbursement: senior in chain approves -> product owner expected allowed"""
    h = _setup_hierarchy(client, db, company_a)
    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["senior_headers"],
        json={"action": "approve"},
    )
    assert res.status_code == 200, f"Senior denied: {res.status_code} {res.text}"


def test_reimbursement_approval_j_inactive_manager_denied(
    client: TestClient, db: Session, company_a: TenantContext
):
    """j) Reimbursement: inactive manager denied -> 401 or 403"""
    h = _setup_hierarchy(client, db, company_a)
    direct_emp = db.get(Employee, uuid.UUID(h["direct"]["id"]))
    assert direct_emp and direct_emp.user_id
    user = db.get(User, direct_emp.user_id)
    assert user
    user.is_active = False
    direct_emp.is_active = False
    db.commit()

    claim_id = _create_pending_reimbursement(client, h["emp_headers"])

    res = client.put(
        f"/api/v1/payroll/reimbursements/{claim_id}",
        headers=h["direct_headers"],
        json={"action": "approve"},
    )
    assert res.status_code in (401, 403), res.text


# =============================================================================
# 5. TIME ENTRY APPROVAL: POST /api/v1/projects/time-entries/{id}/approve
# =============================================================================
def _create_pending_time_entry(
    client: TestClient, company: TenantContext, emp_headers: dict
) -> str:
    proj = client.post(
        "/api/v1/projects",
        headers=company.hr_headers,
        json={"name": f"P-{uuid.uuid4().hex[:4]}", "code": f"PRJ-{uuid.uuid4().hex[:4]}"},
    )
    assert proj.status_code == 201
    proj_id = proj.json()["id"]

    entry = client.post(
        "/api/v1/projects/time-entries",
        headers=emp_headers,
        json={
            "project_id": proj_id,
            "date": date.today().isoformat(),
            "hours": "3.50",
            "description": "Dev work",
        },
    )
    assert entry.status_code == 201, entry.text
    return entry.json()["id"]


def test_time_entry_approval_a_direct_manager_approves(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) Time entry: direct manager approves -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["direct_headers"],
    )
    assert res.status_code == 200, res.text


def test_time_entry_approval_b_non_reporting_manager_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) Time entry: non-reporting manager approves -> expected 403"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["other_mgr_headers"],
    )
    assert res.status_code == 403, res.text


def test_time_entry_approval_c_employee_self_approval_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) Time entry: employee self approval -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["emp_headers"],
    )
    assert res.status_code == 403, res.text


def test_time_entry_approval_d_hr_admin_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) Time entry: hr_admin in own company -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=company_a.hr_headers,
    )
    assert res.status_code == 200, res.text


def test_time_entry_approval_e_cross_company_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """e) Time entry: cross-company approval -> 403 or 404"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=company_b.hr_headers,
    )
    assert res.status_code in (403, 404), res.text


def test_time_entry_approval_f_second_approval_conflict(
    client: TestClient, db: Session, company_a: TenantContext
):
    """f) Time entry: approving already approved time entry -> 409 or clear error"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    first = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["direct_headers"],
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["direct_headers"],
    )
    assert second.status_code in (409, 400), second.text


def test_time_entry_approval_unauthorized_manager_on_already_approved_gets_403(
    client: TestClient, db: Session, company_a: TenantContext
):
    """Unauthorized manager on an already-approved time entry gets 403, not 409."""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    approved = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["direct_headers"],
    )
    assert approved.status_code == 200, approved.text

    unauthorized = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["other_mgr_headers"],
    )
    assert unauthorized.status_code == 403, unauthorized.text


def test_time_entry_approval_g_old_manager_revoked(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) Time entry: after HR changes manager, old manager cannot approve"""
    h = _setup_hierarchy(client, db, company_a)

    client.put(
        f"/api/v1/employees/{h['emp']['id']}",
        headers=company_a.hr_headers,
        json={"reporting_manager_id": h["other_mgr"]["id"]},
    )

    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    old_res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["direct_headers"],
    )
    assert old_res.status_code == 403, old_res.text


def test_time_entry_approval_h_senior_in_chain_allowed_or_report(
    client: TestClient, db: Session, company_a: TenantContext
):
    """h) Time entry: senior in chain approves -> product owner expected allowed"""
    h = _setup_hierarchy(client, db, company_a)
    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["senior_headers"],
    )
    assert res.status_code == 200, f"Senior denied: {res.status_code} {res.text}"


def test_time_entry_approval_j_inactive_manager_denied(
    client: TestClient, db: Session, company_a: TenantContext
):
    """j) Time entry: inactive manager denied -> 401 or 403"""
    h = _setup_hierarchy(client, db, company_a)
    direct_emp = db.get(Employee, uuid.UUID(h["direct"]["id"]))
    assert direct_emp and direct_emp.user_id
    user = db.get(User, direct_emp.user_id)
    assert user
    user.is_active = False
    direct_emp.is_active = False
    db.commit()

    entry_id = _create_pending_time_entry(client, company_a, h["emp_headers"])

    res = client.post(
        f"/api/v1/projects/time-entries/{entry_id}/approve?status_action=approved",
        headers=h["direct_headers"],
    )
    assert res.status_code in (401, 403), res.text


# =============================================================================
# 6. PIP EVALUATION: POST /api/v1/performance/pips/{pip_id}/evaluate
# =============================================================================
def _seed_active_pip(db: Session, company_id: uuid.UUID, emp_id: str) -> str:
    pip = PerformancePIP(
        company_id=company_id,
        employee_id=uuid.UUID(emp_id),
        title="Performance Plan",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        status="active",
    )
    db.add(pip)
    db.commit()
    return str(pip.id)


def test_pip_evaluation_a_direct_manager_approves(
    client: TestClient, db: Session, company_a: TenantContext
):
    """a) PIP: direct manager evaluates -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["direct_headers"],
        json={"outcome": "passed", "outcome_notes": "Great job"},
    )
    assert res.status_code == 200, res.text


def test_pip_evaluation_b_non_reporting_manager_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """b) PIP: non-reporting manager evaluates -> expected 403"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["other_mgr_headers"],
        json={"outcome": "passed", "outcome_notes": "Unauthorized"},
    )
    assert res.status_code == 403, res.text


def test_pip_evaluation_c_employee_self_approval_forbidden(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) PIP: employee self evaluate -> 403"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["emp_headers"],
        json={"outcome": "passed", "outcome_notes": "Self evaluate"},
    )
    assert res.status_code == 403, res.text


def test_pip_evaluation_d_hr_admin_allowed(
    client: TestClient, db: Session, company_a: TenantContext
):
    """d) PIP: hr_admin in own company -> allowed"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=company_a.hr_headers,
        json={"outcome": "passed", "outcome_notes": "HR evaluate"},
    )
    assert res.status_code == 200, res.text


def test_pip_evaluation_e_cross_company_denied(
    client: TestClient, db: Session, company_a: TenantContext, company_b: TenantContext
):
    """e) PIP: cross-company evaluation -> 403 or 404"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=company_b.hr_headers,
        json={"outcome": "passed"},
    )
    assert res.status_code in (403, 404), res.text


def test_pip_evaluation_f_second_approval_conflict(
    client: TestClient, db: Session, company_a: TenantContext
):
    """f) PIP: evaluating already evaluated PIP -> 409 or clear error"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    first = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["direct_headers"],
        json={"outcome": "passed"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["direct_headers"],
        json={"outcome": "passed"},
    )
    assert second.status_code in (409, 400), second.text


def test_pip_evaluation_unauthorized_manager_on_already_evaluated_gets_403(
    client: TestClient, db: Session, company_a: TenantContext
):
    """Unauthorized manager on an already-evaluated PIP gets 403, not 409."""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    evaluated = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["direct_headers"],
        json={"outcome": "passed"},
    )
    assert evaluated.status_code == 200, evaluated.text

    unauthorized = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["other_mgr_headers"],
        json={"outcome": "passed"},
    )
    assert unauthorized.status_code == 403, unauthorized.text


def test_pip_evaluation_g_old_manager_revoked(
    client: TestClient, db: Session, company_a: TenantContext
):
    """g) PIP: after HR changes manager, old manager cannot evaluate"""
    h = _setup_hierarchy(client, db, company_a)

    client.put(
        f"/api/v1/employees/{h['emp']['id']}",
        headers=company_a.hr_headers,
        json={"reporting_manager_id": h["other_mgr"]["id"]},
    )

    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    old_res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["direct_headers"],
        json={"outcome": "passed"},
    )
    assert old_res.status_code == 403, old_res.text


def test_pip_evaluation_h_senior_in_chain_allowed_or_report(
    client: TestClient, db: Session, company_a: TenantContext
):
    """h) PIP: senior in chain evaluates -> product owner expected allowed"""
    h = _setup_hierarchy(client, db, company_a)
    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["senior_headers"],
        json={"outcome": "passed"},
    )
    assert res.status_code == 200, f"Senior denied: {res.status_code} {res.text}"


def test_pip_evaluation_j_inactive_manager_denied(
    client: TestClient, db: Session, company_a: TenantContext
):
    """j) PIP: inactive manager denied -> 401 or 403"""
    h = _setup_hierarchy(client, db, company_a)
    direct_emp = db.get(Employee, uuid.UUID(h["direct"]["id"]))
    assert direct_emp and direct_emp.user_id
    user = db.get(User, direct_emp.user_id)
    assert user
    user.is_active = False
    direct_emp.is_active = False
    db.commit()

    pip_id = _seed_active_pip(db, company_a.company_id, h["emp"]["id"])

    res = client.post(
        f"/api/v1/performance/pips/{pip_id}/evaluate",
        headers=h["direct_headers"],
        json={"outcome": "passed"},
    )
    assert res.status_code in (401, 403), res.text


# =============================================================================
# 7. DEPARTMENT CLEARANCE: PUT /api/v1/employees/{employee_id}/fnf/clearance
# =============================================================================
def _setup_clearance_environment(client: TestClient, db: Session, company: TenantContext):
    # IT Department with clearance_function = 'it'
    dept_it_res = client.post(
        "/api/v1/departments",
        headers=company.hr_headers,
        json={"name": f"IT-{uuid.uuid4().hex[:4]}", "clearance_function": "it"},
    )
    assert dept_it_res.status_code == 201
    dept_it_id = dept_it_res.json()["id"]

    # Finance Department with clearance_function = 'finance'
    dept_fin_res = client.post(
        "/api/v1/departments",
        headers=company.hr_headers,
        json={"name": f"Finance-{uuid.uuid4().hex[:4]}", "clearance_function": "finance"},
    )
    assert dept_fin_res.status_code == 201
    dept_fin_id = dept_fin_res.json()["id"]

    # IT Manager in IT department
    it_mgr = _create_employee(
        client,
        company.hr_headers,
        email=f"itmgr-{uuid.uuid4().hex[:6]}@example.com",
        department_id=dept_it_id,
    )
    it_mgr_headers = _link_user_to_employee(db, company.company_id, it_mgr["id"], UserRole.manager)

    # Finance Manager in Finance department
    fin_mgr = _create_employee(
        client,
        company.hr_headers,
        email=f"finmgr-{uuid.uuid4().hex[:6]}@example.com",
        department_id=dept_fin_id,
    )
    fin_mgr_headers = _link_user_to_employee(
        db, company.company_id, fin_mgr["id"], UserRole.manager
    )

    # Departing employee
    emp = _create_employee(
        client, company.hr_headers, email=f"res-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp_headers = _link_user_to_employee(db, company.company_id, emp["id"], UserRole.employee)

    # Submit and approve resignation to prepare for clearance
    client.post(
        f"/api/v1/employees/{emp['id']}/resignation",
        headers=emp_headers,
        json={"resignation_date": "2026-09-01", "last_working_date": "2026-10-01"},
    )
    client.put(
        f"/api/v1/employees/{emp['id']}/resignation/approve",
        headers=company.hr_headers,
        json={"approved": True},
    )

    return {
        "it_mgr_headers": it_mgr_headers,
        "fin_mgr_headers": fin_mgr_headers,
        "emp": emp,
        "emp_headers": emp_headers,
    }


def test_clearance_i_role_specific_signing_and_cross_department_rejection(
    client: TestClient, db: Session, company_a: TenantContext
):
    """i) Clearance: IT manager signs IT clearance,
    but Finance manager is rejected for IT clearance
    """
    env = _setup_clearance_environment(client, db, company_a)
    emp_id = env["emp"]["id"]

    # Finance manager tries to sign IT clearance -> 403
    fin_try_it = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        headers=env["fin_mgr_headers"],
        json={"it_clearance": True},
    )
    assert fin_try_it.status_code == 403, fin_try_it.text

    # IT manager tries to sign Finance clearance -> 403
    it_try_fin = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        headers=env["it_mgr_headers"],
        json={"finance_clearance": True},
    )
    assert it_try_fin.status_code == 403, it_try_fin.text

    # IT manager signs IT clearance -> 200
    it_sign = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        headers=env["it_mgr_headers"],
        json={"it_clearance": True},
    )
    assert it_sign.status_code == 200, it_sign.text

    # Finance manager signs Finance clearance -> 200
    fin_sign = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        headers=env["fin_mgr_headers"],
        json={"finance_clearance": True},
    )
    assert fin_sign.status_code == 200, fin_sign.text


def test_clearance_c_employee_cannot_self_clear(
    client: TestClient, db: Session, company_a: TenantContext
):
    """c) Clearance: departing employee cannot sign off on own clearance"""
    env = _setup_clearance_environment(client, db, company_a)
    emp_id = env["emp"]["id"]

    res = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        headers=env["emp_headers"],
        json={"it_clearance": True},
    )
    assert res.status_code == 403, res.text


# =============================================================================
# 8. PRIVILEGE ESCALATION TEST: PUT /api/v1/employees/{own_id}
# =============================================================================
def test_privilege_escalation_by_employee_blocked(
    client: TestClient, db: Session, company_a: TenantContext
):
    """Privilege escalation: employee attempts to change role,
    reporting manager, salary, or status via PUT
    """
    mgr = _create_employee(
        client, company_a.hr_headers, email=f"mgr-{uuid.uuid4().hex[:6]}@example.com"
    )
    emp = _create_employee(
        client,
        company_a.hr_headers,
        email=f"emp-{uuid.uuid4().hex[:6]}@example.com",
        reporting_manager_id=mgr["id"],
    )
    headers_emp = _link_user_to_employee(db, company_a.company_id, emp["id"], UserRole.employee)

    fake_mgr_id = str(uuid.uuid4())
    res = client.put(
        f"/api/v1/employees/{emp['id']}",
        headers=headers_emp,
        json={
            "reporting_manager_id": fake_mgr_id,
            "level": "L10",
            "position": "CEO",
            "first_name": "HackedName",
            # Fields ignored or rejected
        },
    )
    # The server should either reject with 403 or ignore restricted fields
    assert res.status_code in (403, 400), f"Response was: {res.status_code} {res.text}"

    # Re-read employee to verify nothing escalated
    get_res = client.get(f"/api/v1/employees/{emp['id']}", headers=headers_emp)
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["reporting_manager_id"] == mgr["id"], "Reporting manager was modified!"
    assert data["position"] != "CEO", "Position was modified!"
