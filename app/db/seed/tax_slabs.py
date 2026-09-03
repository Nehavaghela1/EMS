"""Seeds the `tax_slabs` table (Spec 7.6) — government-defined, platform-
managed, no RLS, the same treatment `industry_presets` gets.

FY 2026-2027 (AY 2027-28), both regimes. Verified 2026-09-03 directly
against the Income Tax Department's own e-filing portal
(incometax.gov.in/iec/foportal/help/individual/return-applicable-1),
confirmed unchanged from FY 2025-26 by Budget 2026 (February 2026, which
made no change to slabs, standard deduction, 87A rebate, surcharge, or
cess for either regime) — so FY 2025-2026 is seeded too, with the same
figures, purely so a payroll date in the prior financial year resolves to
a real row under that year's own `financial_year` key rather than a
lookup miss. `surcharge_rules` also carries the standard deduction and the
Section 87A rebate, since neither has its own column or table this
session.

Run directly: `python -m app.db.seed.tax_slabs`
Or import `seed_tax_slabs(db)` and call it — idempotent (upsert by
country + financial_year + regime + min_income), safe to run repeatedly.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.modules.payroll.models import TaxRegime, TaxSlab

_SOURCE_NOTE = (
    "Income Tax Department's own e-filing portal "
    "(incometax.gov.in/iec/foportal/help/individual/return-applicable-1), fetched "
    "directly 2026-09-03. FY 2026-27/AY 2027-28 confirmed unchanged from FY 2025-26 "
    "by Budget 2026 (February 2026)."
)

_CESS = Decimal("4.000")

# Shared across every row of a given regime (Spec 7.6 gives surcharge_rules
# no per-bracket shape of its own — the whole regime's non-slab figures ride
# along here). Every rupee figure is a Decimal-shaped string, not a number,
# so nothing downstream is tempted to do float arithmetic on it.
_NEW_REGIME_EXTRAS = {
    "standard_deduction": "75000.00",
    "rebate_87a": {"income_limit": "1200000.00", "max_rebate": "60000.00"},
    "surcharge": [
        {"income_min": "5000000.00", "income_max": "10000000.00", "rate_percent": "10.000"},
        {"income_min": "10000000.00", "income_max": "20000000.00", "rate_percent": "15.000"},
        {"income_min": "20000000.00", "income_max": "50000000.00", "rate_percent": "25.000"},
        {"income_min": "50000000.00", "income_max": None, "rate_percent": "25.000"},
    ],
}

_OLD_REGIME_EXTRAS = {
    "standard_deduction": "50000.00",
    "rebate_87a": {"income_limit": "500000.00", "max_rebate": "12500.00"},
    "surcharge": [
        {"income_min": "5000000.00", "income_max": "10000000.00", "rate_percent": "10.000"},
        {"income_min": "10000000.00", "income_max": "20000000.00", "rate_percent": "15.000"},
        {"income_min": "20000000.00", "income_max": "50000000.00", "rate_percent": "25.000"},
        {"income_min": "50000000.00", "income_max": None, "rate_percent": "37.000"},
    ],
}

_NEW_REGIME_BRACKETS = [
    (Decimal("0.00"), Decimal("400000.00"), Decimal("0.000")),
    (Decimal("400000.01"), Decimal("800000.00"), Decimal("5.000")),
    (Decimal("800000.01"), Decimal("1200000.00"), Decimal("10.000")),
    (Decimal("1200000.01"), Decimal("1600000.00"), Decimal("15.000")),
    (Decimal("1600000.01"), Decimal("2000000.00"), Decimal("20.000")),
    (Decimal("2000000.01"), Decimal("2400000.00"), Decimal("25.000")),
    (Decimal("2400000.01"), None, Decimal("30.000")),
]

_OLD_REGIME_BRACKETS = [
    (Decimal("0.00"), Decimal("250000.00"), Decimal("0.000")),
    (Decimal("250000.01"), Decimal("500000.00"), Decimal("5.000")),
    (Decimal("500000.01"), Decimal("1000000.00"), Decimal("20.000")),
    (Decimal("1000000.01"), None, Decimal("30.000")),
]

# (financial_year, effective_from) — both years carry identical brackets;
# see the module docstring for why FY 2025-2026 is seeded at all.
_FINANCIAL_YEARS = [
    ("2025-2026", date(2025, 4, 1)),
    ("2026-2027", date(2026, 4, 1)),
]


def _rows() -> list[dict]:
    rows = []
    for financial_year, effective_from in _FINANCIAL_YEARS:
        for min_income, max_income, rate in _NEW_REGIME_BRACKETS:
            rows.append(
                {
                    "financial_year": financial_year,
                    "regime": TaxRegime.new,
                    "min_income": min_income,
                    "max_income": max_income,
                    "rate_percent": rate,
                    "cess_percent": _CESS,
                    "surcharge_rules": _NEW_REGIME_EXTRAS,
                    "effective_from": effective_from,
                    "source_note": _SOURCE_NOTE,
                }
            )
        for min_income, max_income, rate in _OLD_REGIME_BRACKETS:
            rows.append(
                {
                    "financial_year": financial_year,
                    "regime": TaxRegime.old,
                    "min_income": min_income,
                    "max_income": max_income,
                    "rate_percent": rate,
                    "cess_percent": _CESS,
                    "surcharge_rules": _OLD_REGIME_EXTRAS,
                    "effective_from": effective_from,
                    "source_note": _SOURCE_NOTE,
                }
            )
    return rows


def seed_tax_slabs(db: Session) -> None:
    """Idempotent — upsert by (country, financial_year, regime, min_income),
    safe to re-run."""
    for row in _rows():
        existing = (
            db.query(TaxSlab)
            .filter_by(
                country="IN",
                financial_year=row["financial_year"],
                regime=row["regime"],
                min_income=row["min_income"],
            )
            .first()
        )
        if existing is None:
            db.add(TaxSlab(country="IN", **row))
        else:
            existing.max_income = row["max_income"]
            existing.rate_percent = row["rate_percent"]
            existing.cess_percent = row["cess_percent"]
            existing.surcharge_rules = row["surcharge_rules"]
            existing.effective_from = row["effective_from"]
            existing.source_note = row["source_note"]
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_tax_slabs(session)
        print(f"Seeded {len(_rows())} tax_slabs rows.")
