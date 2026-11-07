"""Seeds the `statutory_rates` table (5.2) - government-defined, platform-managed, no RLS, like
`pt_slabs`. Every figure and link below comes from the project's source table, checked by
reading the official pages on 2026-11-04; nothing here is from a publisher.

EPF (scheme `epf`): employee 12.000, employer 12.000 in total (3.67 to EPF + 8.33 to EPS),
EDLI 0.500; wage ceiling 15000.00 until 2026-09-16 and 25000.00 from 2026-09-17. The EPF
administrative charge is NOT seeded (the sources disagree: left null). Earlier history is not
seeded.
ESI (scheme `esi`): employee 0.750, employer 3.250, wage ceiling 21000.00 from 2019-07-01;
employees with an average daily wage up to 176.00 pay no employee share (formula is an
assumption, written in the row note).

Run directly: `python -m app.db.seed.statutory_rates`
Or import `seed_statutory_rates(db)` - idempotent (upsert by scheme + effective_from), safe to
run repeatedly. A row without a source, or with a link outside the government list, raises.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.official_sources import validate_seed_row
from app.db.session import SessionLocal
from app.modules.payroll.models import StatutoryRate

_VERIFIED_ON = date(2026, 11, 4)

_EPF_ROW_1_NOTE = (
    "12% employee and 12% employer of wages, wage ceiling Rs 15,000 "
    "(https://pmvbry.epfindia.gov.in/epf-scheme/). Also: "
    "https://www.epfindia.gov.in/site_docs/PDFs/MiscPDFs/Employer_Information_Booklet.pdf "
    "(EPF 3.67 / EPS 8.33 split, ceiling 15,000, booklet dated 1 Nov 2022); "
    "https://pmvbry.epfindia.gov.in/insurance-scheme-edli/ (EDLI 0.5%). The EPF "
    "administrative charge is not seeded: the sources found disagree, so the figure is "
    "unconfirmed and the column stays empty. Earlier history is not seeded: this row starts "
    "on 2017-04-01."
)

_EPF_ROW_2_NOTE = (
    "Wage ceiling raised from Rs 15,000 to Rs 25,000, effective 17 September 2026; rates "
    "unchanged (https://www.pib.gov.in/PressReleasePage.aspx?PRID=2313790&reg=48&lang=2). Also: "
    "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2310811&reg=48&lang=2 (Cabinet approval, "
    "16 Sep 2026); https://www.pib.gov.in/PressReleasePage.aspx?PRID=2314111&lang=1&reg=3 "
    "(gazette notification dated 17 Sep 2026)."
)

_ESI_NOTE = (
    "0.75% employee and 3.25% employer contribution, effective 01.07.2019 "
    "(https://esic.gov.in/contribution). Also: https://esic.gov.in/coverage (wage ceiling Rs "
    "21,000 per month, Rs 25,000 for persons with disability, effective 1 January 2017). "
    "Daily-wage exemption: esic.gov.in/contribution states that employees whose average daily "
    "wage is up to Rs 176 pay no employee share while the employer still pays its own; the "
    "page does not give a date for the 176 figure. The page does not define how the average "
    "daily wage is computed. This system uses the ESI-liable earned gross of the payroll month "
    "divided by the calendar days of that month. That formula is an assumption, to be "
    "confirmed against the ESI (Central) Rules, 1950."
)

_EPF_SPLIT = {
    "employee_rate": Decimal("12.000"),
    "employer_rate": Decimal("12.000"),
    "employer_epf_rate": Decimal("3.670"),
    "employer_eps_rate": Decimal("8.330"),
    "edli_rate": Decimal("0.500"),
    "admin_charge_rate": None,  # not seeded: unconfirmed (see the row note)
    "employee_exempt_daily_wage": None,
}

RATE_ROWS: list[dict] = [
    {
        "scheme": "epf",
        **_EPF_SPLIT,
        "wage_ceiling": Decimal("15000.00"),
        "effective_from": date(2017, 4, 1),
        "effective_to": date(2026, 9, 16),
        "source_url": "https://pmvbry.epfindia.gov.in/epf-scheme/",
        "source_title": "EPFO - EPF Scheme: contribution rates and wage ceiling Rs 15,000",
        "source_note": _EPF_ROW_1_NOTE,
        "verified_on": _VERIFIED_ON,
    },
    {
        "scheme": "epf",
        **_EPF_SPLIT,
        "wage_ceiling": Decimal("25000.00"),
        "effective_from": date(2026, 9, 17),
        "effective_to": None,
        "source_url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2313790&reg=48&lang=2",
        "source_title": "PIB - EPF wage ceiling raised from Rs 15,000 to Rs 25,000 (17 Sep 2026)",
        "source_note": _EPF_ROW_2_NOTE,
        "verified_on": _VERIFIED_ON,
    },
    {
        "scheme": "esi",
        "employee_rate": Decimal("0.750"),
        "employer_rate": Decimal("3.250"),
        "employer_epf_rate": None,
        "employer_eps_rate": None,
        "edli_rate": None,
        "admin_charge_rate": None,
        "employee_exempt_daily_wage": Decimal("176.00"),
        "wage_ceiling": Decimal("21000.00"),
        "effective_from": date(2019, 7, 1),
        "effective_to": None,
        "source_url": "https://esic.gov.in/contribution",
        "source_title": "ESIC - contribution rates (effective 01.07.2019)",
        "source_note": _ESI_NOTE,
        "verified_on": _VERIFIED_ON,
    },
]

_UPDATED = (
    "employee_rate",
    "employer_rate",
    "wage_ceiling",
    "employer_epf_rate",
    "employer_eps_rate",
    "edli_rate",
    "admin_charge_rate",
    "employee_exempt_daily_wage",
    "effective_to",
    "source_url",
    "source_title",
    "source_note",
    "verified_on",
)


def seed_statutory_rates(db: Session) -> None:
    """Idempotent upsert by (country, scheme, effective_from). Every seeded row is India's.
    Raises before writing anything if a row has no source or a non-official link."""
    for row in RATE_ROWS:
        validate_seed_row(row)
    for row in RATE_ROWS:
        existing = (
            db.query(StatutoryRate)
            .filter_by(country="IN", scheme=row["scheme"], effective_from=row["effective_from"])
            .first()
        )
        if existing is None:
            db.add(StatutoryRate(country="IN", **row))
        else:
            for column in _UPDATED:
                setattr(existing, column, row[column])
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_statutory_rates(session)
        print(f"Seeded {len(RATE_ROWS)} statutory_rates rows.")
