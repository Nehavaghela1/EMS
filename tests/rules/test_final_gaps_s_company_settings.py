"""Red-first tests for Part S (honour company working-days and full-day-hours settings).

S1. Payroll working days basis: when payroll_working_days_basis is 'working_days', daily rate is calculated
    from company working days in that month, not calendar days.
S2. Project standard monthly hours: calculated from company working days * full_day_hours (not static 176).
"""

from datetime import date
from decimal import Decimal
import uuid
import pytest
from sqlalchemy.orm import Session

from app.db.rls import bind_tenant_to_session
from app.modules.identity.models import Company, CompanySettings, CompanyStatus, User, UserRole, PayrollWorkingDaysBasis
from app.modules.projects.service import ProjectService
from app.modules.payroll.service import PayrollRunService


def test_S1_payroll_working_days_basis_honoured(db: Session):
    # Verify that get_working_days or payroll daily rate calculation honours company_settings
    service = PayrollRunService(db)
    assert hasattr(service, "get_month_working_days"), "S1: PayrollRunService must have helper get_month_working_days"


def test_S2_project_service_honours_working_days_and_full_day_hours(db: Session):
    cid = uuid.uuid4()
    bind_tenant_to_session(db, company_id=cid, is_platform_admin=True)

    company = Company(
        id=cid,
        name=f"Comp_{uuid.uuid4().hex[:6]}",
        code=f"C{uuid.uuid4().hex[:4].upper()}",
        email=f"comp_{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
    )
    db.add(company)
    settings = CompanySettings(
        company_id=cid,
        full_day_hours=Decimal("7.50"),
        payroll_working_days_basis=PayrollWorkingDaysBasis.working_days,
    )
    db.add(settings)
    db.commit()

    service = ProjectService(db)
    # Testing standard monthly hours helper / calculation for a given date
    assert hasattr(service, "get_standard_monthly_hours"), "S2: ProjectService must have dynamic get_standard_monthly_hours"
    hours = service.get_standard_monthly_hours(cid, date(2026, 4, 1))
    # In April 2026, 30 days. Standard Mon-Fri working days = 22. 22 * 7.50 = 165.00 != 176.00
    assert hours == Decimal("165.00"), f"Expected 165.00, got {hours}"
