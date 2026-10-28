"""Celery tasks for HR module: employee CSV export, etc."""

import csv
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.csv_safety import csv_safe_cell
from app.db.rls import bind_tenant_to_session
from app.db.session import SessionLocal
from app.modules.hr.models import Employee, EmploymentType
from app.modules.hr.repository import EmployeeRepository
from app.modules.identity.models import CompanyLocation, User, UserRole
from app.workers.celery_app import celery_app

logger = logging.getLogger("app")


@celery_app.task(name="app.workers.tasks.hr.export_employees_csv_task")
def export_employees_csv_task(
    *,
    company_id: str,
    actor_id: str,
    actor_role: str,
    q: str | None = None,
    department_id: str | None = None,
    is_active: bool | None = None,
    level: str | None = None,
    employment_type: str | None = None,
    reporting_manager_id: str | None = None,
    role: str | None = None,
    employee_ids: list[str] | None = None,
) -> dict:
    """13.2: opens its own session and binds tenant context.
    Streams CSV with UTF-8 BOM and formula sanitization.
    Row cap at 50,000.
    """
    db = SessionLocal()
    try:
        cid = uuid.UUID(company_id)
        bind_tenant_to_session(db, company_id=cid, is_platform_admin=False)

        repo = EmployeeRepository(db)
        direct_report_ids = None
        if actor_role == UserRole.manager.value:
            mgr_user_id = uuid.UUID(actor_id)
            mgr_emp = repo.get_by_user_id(cid, mgr_user_id)
            if mgr_emp:
                direct_report_ids = repo.list_direct_report_ids(cid, mgr_emp.id)
            else:
                direct_report_ids = []

        selected_uuids = [uuid.UUID(x) for x in employee_ids] if employee_ids else None
        emp_type_enum = EmploymentType(employment_type) if employment_type else None

        employees = repo.list_for_export(
            company_id=cid,
            q=q,
            department_id=uuid.UUID(department_id) if department_id else None,
            is_active=is_active,
            level=level,
            employment_type=emp_type_enum,
            reporting_manager_id=uuid.UUID(reporting_manager_id) if reporting_manager_id else None,
            role=role,
            employee_ids=selected_uuids,
            direct_report_ids=direct_report_ids,
            limit=50000,
        )

        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        task_id = export_employees_csv_task.request.id or uuid.uuid4().hex
        file_name = f"employees_{cid}_{task_id}.csv"
        file_path = os.path.join(settings.EXPORT_DIR, file_name)

        is_hr_or_owner = actor_role in (UserRole.owner.value, UserRole.hr_admin.value, UserRole.super_admin.value)

        # Build department & location & manager lookup maps
        dept_ids = {e.department_id for e in employees if e.department_id}
        loc_ids = {e.location_id for e in employees if e.location_id}
        mgr_ids = {e.reporting_manager_id for e in employees if e.reporting_manager_id}

        from app.modules.hr.models import Department
        depts = db.query(Department).filter(Department.id.in_(dept_ids)).all() if dept_ids else []
        dept_map = {d.id: d.name for d in depts}

        locs = db.query(CompanyLocation).filter(CompanyLocation.id.in_(loc_ids)).all() if loc_ids else []
        loc_map = {loc.id: loc.name for loc in locs}

        mgrs = db.query(Employee).filter(Employee.id.in_(mgr_ids)).all() if mgr_ids else []
        mgr_map = {m.id: f"{m.first_name} {m.last_name or ''}".strip() for m in mgrs}

        if is_hr_or_owner:
            headers = [
                "Employee Code",
                "First Name",
                "Last Name",
                "Work Email",
                "Department",
                "Position",
                "Level",
                "Employment Type",
                "Reporting Manager",
                "Location",
                "Hire Date",
                "Status",
                "Phone",
                "Personal Email",
            ]
        else:
            headers = [
                "Employee Code",
                "First Name",
                "Last Name",
                "Work Email",
                "Department",
                "Position",
                "Level",
                "Employment Type",
                "Reporting Manager",
                "Location",
                "Hire Date",
                "Status",
            ]

        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for emp in employees:
                status_str = "Active" if emp.is_active else "Inactive"
                dept_name = dept_map.get(emp.department_id, "")
                loc_name = loc_map.get(emp.location_id, "")
                mgr_name = mgr_map.get(emp.reporting_manager_id, "")
                hire_str = emp.hire_date.isoformat() if emp.hire_date else ""

                if is_hr_or_owner:
                    row = [
                        csv_safe_cell(emp.employee_code),
                        csv_safe_cell(emp.first_name),
                        csv_safe_cell(emp.last_name or ""),
                        csv_safe_cell(emp.email),
                        csv_safe_cell(dept_name),
                        csv_safe_cell(emp.position or ""),
                        csv_safe_cell(emp.level or ""),
                        csv_safe_cell(emp.employment_type.value if emp.employment_type else ""),
                        csv_safe_cell(mgr_name),
                        csv_safe_cell(loc_name),
                        csv_safe_cell(hire_str),
                        csv_safe_cell(status_str),
                        csv_safe_cell(emp.phone or ""),
                        csv_safe_cell(emp.personal_email or ""),
                    ]
                else:
                    row = [
                        csv_safe_cell(emp.employee_code),
                        csv_safe_cell(emp.first_name),
                        csv_safe_cell(emp.last_name or ""),
                        csv_safe_cell(emp.email),
                        csv_safe_cell(dept_name),
                        csv_safe_cell(emp.position or ""),
                        csv_safe_cell(emp.level or ""),
                        csv_safe_cell(emp.employment_type.value if emp.employment_type else ""),
                        csv_safe_cell(mgr_name),
                        csv_safe_cell(loc_name),
                        csv_safe_cell(hire_str),
                        csv_safe_cell(status_str),
                    ]
                writer.writerow(row)

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=24)
        download_name = f"employees_{now.strftime('%Y-%m-%d')}.csv"

        logger.info(
            "employees_csv_exported",
            extra={"company_id": company_id, "file_path": file_path, "row_count": len(employees)},
        )
        return {
            "company_id": company_id,
            "requester_id": actor_id,
            "requester_role": actor_role,
            "file_path": file_path,
            "row_count": len(employees),
            "file_name": download_name,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    finally:
        db.close()
