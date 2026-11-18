"""Red-first tests for Part T (Tax slabs cannot change mid-year).

T1. TaxSlab bracketed by financial_year + regime with effective_to.
T2. Approving 5.9 draft for existing FY adds new set and closes old set (effective_to = start - 1 day).
T3. TaxSlabRepository.list_in_force selects only active slabs on on_date (bounded by effective_to).
T4. Mid-year revision must start after current set start date and outside ended periods.
T5. Different financial year gets its own open bracket set without affecting other financial years.
"""

from datetime import date, timedelta
from decimal import Decimal
import uuid
import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.core.exceptions import ConflictError
from app.modules.identity.models import User, UserRole, Company, CompanyStatus
from app.modules.payroll.models import TaxSlab, TaxRegime
from app.modules.payroll.schemas import TaxSlabBracketInput, TaxSlabPostRequest
from app.modules.payroll.repository import TaxSlabRepository
from app.modules.payroll.service import TaxSlabService


@pytest.fixture
def tax_sa(db: Session) -> User:
    cid = uuid.uuid4()
    company = Company(
        id=cid,
        name=f"TaxTest_{uuid.uuid4().hex[:6]}",
        code=f"TT{uuid.uuid4().hex[:4].upper()}",
        email=f"tax_{uuid.uuid4().hex[:6]}@example.com",
        country="IN",
        status=CompanyStatus.active,
    )
    db.add(company)
    db.flush()
    sa = User(
        id=uuid.uuid4(),
        company_id=cid,
        email=f"tax_sa_{uuid.uuid4().hex[:6]}@example.com",
        role=UserRole.super_admin,
        hashed_password="pw",
        is_active=True,
    )
    db.add(sa)
    db.commit()
    return sa


def _tax_req(fy: str, start: date, max_inc: Decimal) -> TaxSlabPostRequest:
    return TaxSlabPostRequest(
        country="IN",
        financial_year=fy,
        regime=TaxRegime.new,
        effective_from=start,
        cess_percent=Decimal("4.00"),
        source_url="https://incometax.gov.in/rates",
        source_title="Tax Rates Notification",
        verified_on=utcnow().date(),
        brackets=[
            TaxSlabBracketInput(min_income=Decimal("0.00"), max_income=max_inc, rate_percent=Decimal("0.00")),
            TaxSlabBracketInput(min_income=max_inc + Decimal("0.01"), max_income=None, rate_percent=Decimal("5.00")),
        ],
    )


def test_T1_T2_tax_slabs_can_be_closed_and_revised_mid_year(db: Session, tax_sa: User):
    service = TaxSlabService(db)
    repo = TaxSlabRepository(db)

    # Initial bracket set for 2031-2032 starting 2031-04-01
    fy = "2031-2032"
    start1 = date(2031, 4, 1)
    req1 = _tax_req(fy, start1, Decimal("400000.00"))
    set1 = service.add_bracket_set(req1, tax_sa)
    assert len(set1) == 2
    for s in set1:
        assert hasattr(s, "effective_to"), "T1: TaxSlab must have effective_to attribute"
        assert s.effective_to is None

    # Mid-year change starting 2031-10-01
    start2 = date(2031, 10, 1)
    req2 = _tax_req(fy, start2, Decimal("500000.00"))
    # T2: Should succeed without ConflictError and close old rows
    set2 = service.add_bracket_set(req2, tax_sa)
    assert len(set2) == 2

    # Check that set1 rows now have effective_to == 2031-09-30
    for s in set1:
        db.refresh(s)
        assert s.effective_to == start2 - timedelta(days=1), f"T2: old row effective_to was not closed: {s.effective_to}"


def test_T3_list_in_force_respects_effective_to_upper_bound(db: Session, tax_sa: User):
    service = TaxSlabService(db)
    repo = TaxSlabRepository(db)

    fy = "2032-2033"
    start1 = date(2032, 4, 1)
    req1 = _tax_req(fy, start1, Decimal("300000.00"))
    service.add_bracket_set(req1, tax_sa)

    start2 = date(2032, 10, 1)
    req2 = _tax_req(fy, start2, Decimal("400000.00"))
    service.add_bracket_set(req2, tax_sa)

    # In force on 2032-06-01: must return set 1 only (min_income 300000.00 max)
    slabs_june = repo.list_in_force("IN", fy, TaxRegime.new, date(2032, 6, 1))
    assert len(slabs_june) == 2
    assert slabs_june[0].max_income == Decimal("300000.00")

    # In force on 2032-11-01: must return set 2 only (min_income 400000.00 max)
    slabs_nov = repo.list_in_force("IN", fy, TaxRegime.new, date(2032, 11, 1))
    assert len(slabs_nov) == 2
    assert slabs_nov[0].max_income == Decimal("400000.00")


def test_T4_invalid_overlapping_effective_from_rejected(db: Session, tax_sa: User):
    service = TaxSlabService(db)

    fy = "2033-2034"
    start1 = date(2033, 4, 1)
    req1 = _tax_req(fy, start1, Decimal("300000.00"))
    service.add_bracket_set(req1, tax_sa)

    # Overlapping or earlier date must be rejected with ConflictError
    req_bad = _tax_req(fy, date(2033, 3, 1), Decimal("300000.00"))
    with pytest.raises(ConflictError):
        service.add_bracket_set(req_bad, tax_sa)
