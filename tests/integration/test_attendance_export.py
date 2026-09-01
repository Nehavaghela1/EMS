"""WP-09 route 49: the CSV export Celery task's own business logic.

Celery tasks always open their own session against the production
`DATABASE_URL` (Spec 13.2 rule 2) — correct for real usage, but it means a
task can't share the pytest suite's savepoint-isolated `TEST_DATABASE_URL`
session the way a request through `client` can. This test monkeypatches the
task's `SessionLocal` to point at the real, separate test database instead
(the same database `TEST_DATABASE_URL` names), seeds real committed rows
there directly, and calls the task function itself — exercising the exact
same code a real worker runs, just pointed at test data.

The queueing/async plumbing itself (a real worker consuming a real broker
job) is proven separately and for real in test_celery_tasks.py; this file
is about "does the export produce the right CSV," not "does Celery work."
"""

import csv
import os
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.rls import bind_tenant_to_session
from app.modules.hr.models import Employee, EmploymentType
from app.modules.identity.models import Company, CompanySettings, CompanyStatus
from app.modules.time_leave.models import Attendance, AttendanceSource, AttendanceStatus


def test_export_attendance_csv_task_writes_a_real_csv_file(tmp_path, monkeypatch):
    engine = create_engine(settings.TEST_DATABASE_URL)
    monkeypatch.setattr("app.workers.tasks.attendance.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "EXPORT_DIR", str(tmp_path))

    company_id: uuid.UUID | None = None
    try:
        with Session(engine) as setup:
            company = Company(
                name="Export Co",
                code=f"EXPCO{uuid.uuid4().hex[:5].upper()}",
                email=f"export-{uuid.uuid4().hex[:6]}@example.com",
                status=CompanyStatus.active,
            )
            setup.add(company)
            setup.flush()
            bind_tenant_to_session(setup, company_id=company.id, is_platform_admin=False)
            setup.add(CompanySettings(company_id=company.id))

            employee = Employee(
                company_id=company.id,
                employee_code="EXPCO-0001",
                first_name="Exp",
                last_name="Orter",
                email="exp@exportco.com",
                hire_date=date(2024, 1, 1),
                employment_type=EmploymentType.full_time,
            )
            setup.add(employee)
            setup.flush()
            setup.add(
                Attendance(
                    company_id=company.id,
                    employee_id=employee.id,
                    date=date(2024, 3, 1),
                    status=AttendanceStatus.present,
                    source=AttendanceSource.web,
                    hours_worked=Decimal("8.00"),
                )
            )
            setup.commit()
            company_id = company.id

        from app.workers.tasks.attendance import export_attendance_csv_task

        result = export_attendance_csv_task(company_id=str(company_id))

        assert result["row_count"] == 1
        assert os.path.exists(result["file_path"])
        with open(result["file_path"]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["employee_code"] == "EXPCO-0001"
        assert rows[0]["first_name"] == "Exp"
        assert rows[0]["date"] == "2024-03-01"
        assert rows[0]["hours_worked"] == "8.00"
    finally:
        if company_id is not None:
            with Session(engine) as cleanup:
                bind_tenant_to_session(cleanup, company_id=company_id, is_platform_admin=True)
                cleanup.query(Attendance).filter(Attendance.company_id == company_id).delete()
                cleanup.query(Employee).filter(Employee.company_id == company_id).delete()
                cleanup.query(CompanySettings).filter(
                    CompanySettings.company_id == company_id
                ).delete()
                cleanup.query(Company).filter(Company.id == company_id).delete()
                cleanup.commit()
        engine.dispose()
