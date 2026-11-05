"""Seeds the `pt_slabs` table (Spec 7.6) — government-defined, platform-managed,
no RLS, the same treatment `industry_presets` gets.

Gujarat only (5.2). Source: the Gujarat Commercial Tax Department's schedule "Rate of Profession
Tax", Entry 1, effective 01/04/2022 (page updated 14/02/2024), read on 2026-11-04. Monthly salary
up to and including 12000.00 pays 0.00; more than 12000.00 pays 200.00, so 12000.00 -> 0.00 and
12000.01 -> 200.00. The earlier (pre-2022) structure is not seeded: no official page supports its
dates, so a payroll month before 2022-04-01 has no professional-tax row and a run stops with a
clear message instead of guessing.

Run directly: `python -m app.db.seed.pt_slabs`
Or import `seed_pt_slabs(db)` and call it — idempotent (upsert by
state + income_min + effective_from), safe to run repeatedly. A row without a source, or with a
link outside the government list, raises.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.official_sources import validate_seed_row
from app.db.session import SessionLocal
from app.modules.payroll.models import PtSlab

_SOURCE_URL = (
    "https://commercialtax.gujarat.gov.in/vatwebsite/download/schedule/Rate_of_Profession_Tax.pdf"
)
_SOURCE_TITLE = (
    "Gujarat Commercial Tax Department - Rate of Profession Tax (Entry 1, effective 01/04/2022)"
)
_NOTE = (
    "Gujarat Commercial Tax Department schedule of professional tax rates, Entry 1, effective "
    "01/04/2022 (page updated 14/02/2024): monthly salary up to and including 12000.00 pays "
    "0.00; more than 12000.00 pays 200.00 (12000.00 -> 0.00, 12000.01 -> 200.00). "
    f"Source: {_SOURCE_URL}"
)
_START = date(2022, 4, 1)
_VERIFIED_ON = date(2026, 11, 4)

GUJARAT_SLABS: list[dict] = [
    {
        "income_min": Decimal("0.00"),
        "income_max": Decimal("12000.00"),
        "monthly_amount": Decimal("0.00"),
        "effective_from": _START,
        "effective_to": None,
        "source_url": _SOURCE_URL,
        "source_title": _SOURCE_TITLE,
        "source_note": _NOTE,
        "verified_on": _VERIFIED_ON,
    },
    {
        "income_min": Decimal("12000.01"),
        "income_max": None,
        "monthly_amount": Decimal("200.00"),
        "effective_from": _START,
        "effective_to": None,
        "source_url": _SOURCE_URL,
        "source_title": _SOURCE_TITLE,
        "source_note": _NOTE,
        "verified_on": _VERIFIED_ON,
    },
]


def seed_pt_slabs(db: Session) -> None:
    """Idempotent — upsert by (state, income_min, effective_from), safe to
    re-run."""
    for row in GUJARAT_SLABS:
        validate_seed_row(row)
    for row in GUJARAT_SLABS:
        existing = (
            db.query(PtSlab)
            .filter_by(
                state="Gujarat",
                income_min=row["income_min"],
                effective_from=row["effective_from"],
            )
            .first()
        )
        if existing is None:
            db.add(PtSlab(state="Gujarat", **row))
        else:
            existing.income_max = row["income_max"]
            existing.monthly_amount = row["monthly_amount"]
            existing.effective_to = row["effective_to"]
            existing.source_url = row["source_url"]
            existing.source_title = row["source_title"]
            existing.source_note = row["source_note"]
            existing.verified_on = row["verified_on"]
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_pt_slabs(session)
        print(f"Seeded {len(GUJARAT_SLABS)} pt_slabs rows (Gujarat).")
