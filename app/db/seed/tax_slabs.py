"""Seeds the `tax_slabs` table (Spec 7.6) — government-defined, platform-managed,
no RLS, the same treatment `industry_presets` gets.

Financial years 2025-2026 and 2026-2027 carry the same figures, both regimes, from the project's
source table (official pages read on 2026-11-04):

* New regime: 0-4L nil, 4-8L 5%, 8-12L 10%, 12-16L 15%, 16-20L 20%, 20-24L 25%, above 24L 30%.
  Standard deduction 75,000. Rebate under 87A up to income 12,00,000, maximum 60,000. Cess 4%.
  Surcharge 10% (50 lakh to 1 crore), 15% (1 to 2 crore), 25% above 2 crore.
* Old regime: 0-2.5L nil, 2.5-5L 5%, 5-10L 20%, above 10L 30%. Rebate 87A up to income 5,00,000,
  maximum 12,500. Cess 4%. Surcharge 10% / 15% / 25% / 37% (50 lakh to 1 crore / 1 to 2 crore /
  2 to 5 crore / above 5 crore). Standard deduction 50,000 was NOT re-verified against an
  official page on 2026-11-04 (said plainly in every old-regime row's note).

FY 2026-2027 "unchanged" is taken from the Finance Bill 2026 explanatory memo and the Union
Budget 2026-27 summary and needs a human check against the Finance Act 2026 text.
`surcharge_rules` carries the standard deduction, the 87A rebate and the surcharge slabs.

Run directly: `python -m app.db.seed.tax_slabs`
Or import `seed_tax_slabs(db)` and call it — idempotent (upsert by
country + financial_year + regime + min_income), safe to run repeatedly. A row without a source,
or with a link outside the government list, raises.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.official_sources import validate_seed_row
from app.db.session import SessionLocal
from app.modules.payroll.models import TaxRegime, TaxSlab

_CESS = Decimal("4.000")
_VERIFIED_ON = date(2026, 11, 4)

_OLD_STD_DEDUCTION_NOTE = (
    "The old-regime standard deduction of 50,000 was not re-verified against an official page "
    "on 2026-11-04."
)

_FY_2025_NOTE = (
    "New regime slabs, standard deduction 75,000 and no tax up to 12 lakh (Union Budget, "
    "1 Feb 2025). Also: https://www.incometaxindia.gov.in/w/tax-rates%E2%80%8B (slabs by "
    "assessment year, old regime, surcharge, cess, 87A rebate old regime 12,500)."
)

_FY_2026_NOTE = (
    "Finance Bill 2026 explanatory memo: no change proposed in tax rates. Also: "
    "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/feb/doc202621776101.pdf "
    "(Union Budget 2026-27 summary: no slab change listed). 'Unchanged for FY 2026-27' is "
    "taken from those two documents and needs a human check against the Finance Act 2026 text."
)

# Shared across every row of a given regime (Spec 7.6 gives surcharge_rules no per-bracket
# shape of its own — the whole regime's non-slab figures ride along here). Every rupee figure
# is a Decimal-shaped string, not a number, so nothing downstream does float arithmetic on it.
_NEW_REGIME_EXTRAS = {
    "standard_deduction": "75000.00",
    "rebate_87a": {"income_limit": "1200000.00", "max_rebate": "60000.00"},
    "surcharge": [
        {"income_min": "5000000.00", "income_max": "10000000.00", "rate_percent": "10.000"},
        {"income_min": "10000000.00", "income_max": "20000000.00", "rate_percent": "15.000"},
        {"income_min": "20000000.00", "income_max": None, "rate_percent": "25.000"},
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

# (financial_year, effective_from, source_url, source_title, source_note)
_FINANCIAL_YEARS = [
    (
        "2025-2026",
        date(2025, 4, 1),
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2098406&reg=3&lang=2",
        "PIB - Union Budget 2025: new regime slabs, standard deduction 75,000, nil to 12 lakh",
        _FY_2025_NOTE,
    ),
    (
        "2026-2027",
        date(2026, 4, 1),
        "https://www.indiabudget.gov.in/doc/memo.pdf",
        "Finance Bill 2026 explanatory memo - no change proposed in tax rates",
        _FY_2026_NOTE,
    ),
]


def _rows() -> list[dict]:
    rows = []
    for financial_year, effective_from, url, title, note in _FINANCIAL_YEARS:
        for regime, brackets, extras, regime_note in (
            (TaxRegime.new, _NEW_REGIME_BRACKETS, _NEW_REGIME_EXTRAS, ""),
            (TaxRegime.old, _OLD_REGIME_BRACKETS, _OLD_REGIME_EXTRAS, _OLD_STD_DEDUCTION_NOTE),
        ):
            full_note = f"{note} {regime_note}".strip()
            for min_income, max_income, rate in brackets:
                rows.append(
                    {
                        "financial_year": financial_year,
                        "regime": regime,
                        "min_income": min_income,
                        "max_income": max_income,
                        "rate_percent": rate,
                        "cess_percent": _CESS,
                        "surcharge_rules": extras,
                        "effective_from": effective_from,
                        "source_url": url,
                        "source_title": title,
                        "source_note": full_note,
                        "verified_on": _VERIFIED_ON,
                    }
                )
    return rows


def seed_tax_slabs(db: Session) -> None:
    """Idempotent — upsert by (country, financial_year, regime, min_income),
    safe to re-run."""
    rows = _rows()
    for row in rows:
        validate_seed_row(row)
    for row in rows:
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
            existing.source_url = row["source_url"]
            existing.source_title = row["source_title"]
            existing.source_note = row["source_note"]
            existing.verified_on = row["verified_on"]
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_tax_slabs(session)
        print(f"Seeded {len(_rows())} tax_slabs rows.")
