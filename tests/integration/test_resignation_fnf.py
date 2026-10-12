from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.test_employees import _create_employee


def test_resignation_and_fnf_workflow(client: TestClient, db: Session, company_a):
    hr_headers = company_a.hr_headers
    emp = _create_employee(client, hr_headers, email="resigning@example.com")
    emp_id = emp["id"]
    assert emp["notice_period_days"] == 30

    # 1. Submit early resignation: 2026-09-17 to 2026-10-01 (14 days served)
    # Expected shortfall = 30 - 14 = 16 days
    res_sub = client.post(
        f"/api/v1/employees/{emp_id}/resignation",
        json={
            "resignation_date": "2026-09-17",
            "last_working_date": "2026-10-01",
            "reason": "Better opportunity",
        },
        headers=hr_headers,
    )
    assert res_sub.status_code == 200, res_sub.text
    emp_res = res_sub.json()
    assert emp_res["resignation_status"] == "submitted"
    assert emp_res["notice_recovery_days"] == 16

    # 2. List resignations
    res_list = client.get("/api/v1/employees/resignations", headers=hr_headers)
    assert res_list.status_code == 200
    ids = [r["id"] for r in res_list.json()]
    assert emp_id in ids

    # 3. Approve resignation with notice recovery (16 days shortfall)
    res_app = client.put(
        f"/api/v1/employees/{emp_id}/resignation/approve",
        json={"approved": True, "notice_waived": False, "notice_recovery_days": 16},
        headers=hr_headers,
    )
    assert res_app.status_code == 200
    assert res_app.json()["resignation_status"] == "approved"
    assert res_app.json()["notice_recovery_days"] == 16
    assert res_app.json()["notice_waived"] is False

    # Create salary structure and assign ₹11,750.00 monthly gross to test exact math
    # CTC = 141,000 (11,750 * 12)
    struct_res = client.post(
        "/api/v1/payroll/structures",
        json={
            "name": "Standard L1 Structure",
            "components": [
                {
                    "code": "BASIC",
                    "name": "Basic Salary",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "percentage_of": "ctc",
                    "value": 50.0,
                    "is_taxable": True,
                    "is_statutory": False,
                    "display_order": 1,
                },
                {
                    "code": "SPECIAL",
                    "name": "Special Allowance",
                    "type": "earning",
                    "calculation_type": "percentage",
                    "percentage_of": "ctc",
                    "value": 50.0,
                    "is_taxable": True,
                    "is_statutory": False,
                    "display_order": 2,
                },
            ],
        },
        headers=hr_headers,
    )
    assert struct_res.status_code == 201, struct_res.text
    struct_id = struct_res.json()["id"]

    sal_assign = client.post(
        f"/api/v1/payroll/employees/{emp_id}/assign",
        json={
            "structure_id": struct_id,
            "ctc": 141000.00,  # 141,000 annual CTC = 11,750 monthly gross
            "effective_from": "2026-01-01",
        },
        headers=hr_headers,
    )
    assert sal_assign.status_code == 201, sal_assign.text

    # 4. Calculate FnF Settlement
    res_fnf = client.get(f"/api/v1/employees/{emp_id}/fnf", headers=hr_headers)
    assert res_fnf.status_code == 200
    fnf_data = res_fnf.json()
    assert fnf_data["notice_days_required"] == 30
    assert fnf_data["notice_days_served"] == 14
    assert fnf_data["notice_recovery_days"] == 16
    assert Decimal(str(fnf_data["monthly_gross_salary"])) == Decimal("11750.00")
    # Per day salary = 11750 / 30 = 391.67
    assert Decimal(str(fnf_data["per_day_salary"])) == Decimal("391.67")
    # 16 days notice shortfall recovery = 16 * 391.67 = 6266.72
    assert Decimal(str(fnf_data["notice_recovery_amount"])) == Decimal("6266.72")
    # 1 day unpaid salary = 1 * 391.67 = 391.67
    assert Decimal(str(fnf_data["unpaid_salary_days"])) == 1
    assert Decimal(str(fnf_data["unpaid_salary_amount"])) == Decimal("391.67")
    assert "total_settlement_amount" in fnf_data

    # 5. Test Waive Notice behavior
    res_waive = client.put(
        f"/api/v1/employees/{emp_id}/resignation/approve",
        json={"approved": True, "notice_waived": True, "notice_recovery_days": 0},
        headers=hr_headers,
    )
    assert res_waive.status_code == 200
    assert res_waive.json()["notice_recovery_days"] == 0
    assert res_waive.json()["notice_waived"] is True

    fnf_waived = client.get(f"/api/v1/employees/{emp_id}/fnf", headers=hr_headers)
    assert fnf_waived.status_code == 200
    assert fnf_waived.json()["notice_recovery_days"] == 0
    assert Decimal(str(fnf_waived.json()["notice_recovery_amount"])) == Decimal("0.00")


def test_department_clearance_function_authorization(client: TestClient, db: Session, company_a):
    from app.core.security import create_access_token, hash_password
    from app.modules.hr.models import Employee
    from app.modules.identity.models import User, UserRole

    hr_headers = company_a.hr_headers

    # 1. Create department "Audit" with null clearance_function
    resp_audit_dept = client.post(
        "/api/v1/departments",
        json={"name": "Audit", "description": "Internal Audit"},
        headers=hr_headers,
    )
    assert resp_audit_dept.status_code == 201
    audit_dept_id = resp_audit_dept.json()["id"]
    assert resp_audit_dept.json()["clearance_function"] is None

    # 2. Create department "Tech Services" with clearance_function="it"
    resp_it_dept = client.post(
        "/api/v1/departments",
        json={
            "name": "Tech Services",
            "description": "IT Dept",
            "clearance_function": "it",
        },
        headers=hr_headers,
    )
    assert resp_it_dept.status_code == 201
    it_dept_id = resp_it_dept.json()["id"]
    assert resp_it_dept.json()["clearance_function"] == "it"

    # 3. Create manager in Audit department
    audit_emp = _create_employee(
        client,
        hr_headers,
        email="audit-mgr@example.com",
        department_id=audit_dept_id,
    )
    audit_user = User(
        company_id=company_a.company_id,
        email="audit-mgr-user@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(audit_user)
    db.flush()
    db.query(Employee).filter(Employee.id == audit_emp["id"]).update({"user_id": audit_user.id})
    db.commit()
    audit_token = create_access_token(
        sub=str(audit_user.id),
        company_id=str(company_a.company_id),
        role=UserRole.manager.value,
    )
    audit_mgr_headers = {"Authorization": f"Bearer {audit_token}"}

    # 4. Create manager in Tech Services (IT) department
    it_emp = _create_employee(
        client,
        hr_headers,
        email="it-mgr@example.com",
        department_id=it_dept_id,
    )
    it_user = User(
        company_id=company_a.company_id,
        email="it-mgr-user@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(it_user)
    db.flush()
    db.query(Employee).filter(Employee.id == it_emp["id"]).update({"user_id": it_user.id})
    db.commit()
    it_token = create_access_token(
        sub=str(it_user.id),
        company_id=str(company_a.company_id),
        role=UserRole.manager.value,
    )
    it_mgr_headers = {"Authorization": f"Bearer {it_token}"}

    # 5. Create employee undergoing resignation
    emp = _create_employee(client, hr_headers, email="target-resigning@example.com")
    emp_id = emp["id"]
    res_sub = client.post(
        f"/api/v1/employees/{emp_id}/resignation",
        json={
            "resignation_date": "2026-09-17",
            "last_working_date": "2026-10-01",
            "reason": "Relocation",
        },
        headers=hr_headers,
    )
    assert res_sub.status_code == 200

    # 6. Audit manager (null clearance_function) CANNOT sign off IT clearance -> 403
    res_audit_clear = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        json={"it_clearance": True},
        headers=audit_mgr_headers,
    )
    assert res_audit_clear.status_code == 403
    assert "IT Department Managers" in res_audit_clear.json()["error"]["message"]

    # 7. IT manager (clearance_function='it') CAN sign off IT clearance -> 200
    res_it_clear = client.put(
        f"/api/v1/employees/{emp_id}/fnf/clearance",
        json={"it_clearance": True},
        headers=it_mgr_headers,
    )
    assert res_it_clear.status_code == 200
    assert res_it_clear.json()["it_clearance"] is True


def test_put_department_clearance_function_and_authorization(
    client: TestClient, db: Session, company_a
):
    """Verifies that PUT /departments/{id} accepts and validates clearance_function,
    only HR admins can update it (employees and managers get 403),
    and a manager in a department updated to 'finance' can sign off finance clearance.
    """
    from app.core.security import create_access_token, hash_password
    from app.modules.hr.models import Employee
    from app.modules.identity.models import User, UserRole

    hr_headers = company_a.hr_headers

    # 1. Create a generic department with null clearance_function
    dept_res = client.post(
        "/api/v1/departments",
        json={"name": "Billing Services", "description": "Billing Operations"},
        headers=hr_headers,
    )
    assert dept_res.status_code == 201
    dept_id = dept_res.json()["id"]
    assert dept_res.json()["clearance_function"] is None

    # 2. Create a manager in Billing Services
    mgr_emp = _create_employee(
        client,
        hr_headers,
        email="billing-mgr@example.com",
        department_id=dept_id,
    )
    mgr_user = User(
        company_id=company_a.company_id,
        email="billing-mgr-user@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(mgr_user)
    db.flush()
    db.query(Employee).filter(Employee.id == mgr_emp["id"]).update({"user_id": mgr_user.id})
    db.commit()
    mgr_token = create_access_token(
        sub=str(mgr_user.id),
        company_id=str(company_a.company_id),
        role=UserRole.manager.value,
    )
    mgr_headers = {"Authorization": f"Bearer {mgr_token}"}

    # 3. Create regular employee
    reg_emp = _create_employee(
        client,
        hr_headers,
        email="regular-emp@example.com",
        department_id=dept_id,
    )
    reg_user = User(
        company_id=company_a.company_id,
        email="regular-emp-user@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.employee,
        is_active=True,
    )
    db.add(reg_user)
    db.flush()
    db.query(Employee).filter(Employee.id == reg_emp["id"]).update({"user_id": reg_user.id})
    db.commit()
    reg_token = create_access_token(
        sub=str(reg_user.id),
        company_id=str(company_a.company_id),
        role=UserRole.employee.value,
    )
    reg_headers = {"Authorization": f"Bearer {reg_token}"}

    # 4. Attempt update by employee -> 403 Forbidden
    res_emp_put = client.put(
        f"/api/v1/departments/{dept_id}",
        json={"clearance_function": "finance"},
        headers=reg_headers,
    )
    assert res_emp_put.status_code == 403

    # 5. Attempt update by manager -> 403 Forbidden
    res_mgr_put = client.put(
        f"/api/v1/departments/{dept_id}",
        json={"clearance_function": "finance"},
        headers=mgr_headers,
    )
    assert res_mgr_put.status_code == 403

    # 6. Invalid clearance_function value -> 422 Unprocessable Entity
    res_inv_put = client.put(
        f"/api/v1/departments/{dept_id}",
        json={"clearance_function": "marketing"},
        headers=hr_headers,
    )
    assert res_inv_put.status_code == 422

    # 7. Resigning employee for clearance testing
    target_emp = _create_employee(client, hr_headers, email="target-finance-clear@example.com")
    target_id = target_emp["id"]
    client.post(
        f"/api/v1/employees/{target_id}/resignation",
        json={
            "resignation_date": "2026-09-17",
            "last_working_date": "2026-10-01",
            "reason": "New Offer",
        },
        headers=hr_headers,
    )

    # Before update, Billing manager has null clearance_function -> cannot sign finance clearance
    res_clear_before = client.put(
        f"/api/v1/employees/{target_id}/fnf/clearance",
        json={"finance_clearance": True},
        headers=mgr_headers,
    )
    assert res_clear_before.status_code == 403

    # 8. HR Admin updates department to clearance_function = 'finance'
    res_hr_put = client.put(
        f"/api/v1/departments/{dept_id}",
        json={"clearance_function": "finance"},
        headers=hr_headers,
    )
    assert res_hr_put.status_code == 200
    assert res_hr_put.json()["clearance_function"] == "finance"

    # Now Billing manager has clearance_function = 'finance' -> can sign off finance clearance
    res_clear_after = client.put(
        f"/api/v1/employees/{target_id}/fnf/clearance",
        json={"finance_clearance": True},
        headers=mgr_headers,
    )
    assert res_clear_after.status_code == 200
    assert res_clear_after.json()["finance_clearance"] is True

    # 9. HR Admin can reset clearance_function to null
    res_hr_reset = client.put(
        f"/api/v1/departments/{dept_id}",
        json={"clearance_function": None},
        headers=hr_headers,
    )
    assert res_hr_reset.status_code == 200
    assert res_hr_reset.json()["clearance_function"] is None


def test_department_head_can_review_resignation_using_department_repo(
    client: TestClient, db: Session, company_a
):
    """Verifies that EmployeeService uses department_repo to check dept.head_employee_id
    and authorizes a department head to approve a resignation.
    """
    from app.core.security import create_access_token, hash_password
    from app.modules.hr.models import Employee
    from app.modules.identity.models import User, UserRole

    hr_headers = company_a.hr_headers

    # 1. Create a department
    dept_res = client.post(
        "/api/v1/departments",
        json={"name": "Engineering Operations", "description": "Eng Ops"},
        headers=hr_headers,
    )
    assert dept_res.status_code == 201
    dept_id = dept_res.json()["id"]

    # 2. Create an employee to be Department Head
    head_emp = _create_employee(
        client,
        hr_headers,
        email="dept-head@example.com",
        department_id=dept_id,
    )
    # Assign as head of the department
    dept_upd = client.put(
        f"/api/v1/departments/{dept_id}",
        json={"head_employee_id": head_emp["id"]},
        headers=hr_headers,
    )
    assert dept_upd.status_code == 200

    head_user = User(
        company_id=company_a.company_id,
        email="dept-head-user@example.com",
        hashed_password=hash_password("Test1234pass!"),
        role=UserRole.manager,
        is_active=True,
    )
    db.add(head_user)
    db.flush()
    db.query(Employee).filter(Employee.id == head_emp["id"]).update({"user_id": head_user.id})
    db.commit()

    head_token = create_access_token(
        sub=str(head_user.id),
        company_id=str(company_a.company_id),
        role=UserRole.manager.value,
    )
    head_mgr_headers = {"Authorization": f"Bearer {head_token}"}

    # 3. Create a member of the department (not directly reporting to head)
    subordinate = _create_employee(
        client,
        hr_headers,
        email="subordinate-dev@example.com",
        department_id=dept_id,
    )
    sub_id = subordinate["id"]

    # 4. Subordinate submits resignation
    res_sub = client.post(
        f"/api/v1/employees/{sub_id}/resignation",
        json={
            "resignation_date": "2026-09-20",
            "last_working_date": "2026-10-20",
            "reason": "Moving on",
        },
        headers=hr_headers,
    )
    assert res_sub.status_code == 200

    # 5. Department Head approves resignation (exercises EmployeeService.department_repo.get_by_id)
    app_res = client.put(
        f"/api/v1/employees/{sub_id}/resignation/approve",
        json={"approved": True, "notice_waived": True},
        headers=head_mgr_headers,
    )
    assert app_res.status_code == 200
    assert app_res.json()["resignation_status"] == "approved"
