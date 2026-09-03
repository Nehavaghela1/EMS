"""Seeds the `pt_slabs` table (Spec 7.6) — government-defined, platform-
managed, no RLS, the same treatment `industry_presets` gets.

Gujarat only this session (WP-16's stated primary case). Verified
2026-09-03 against the current rate (a tax-law publisher quoting Gujarat
notification GHN-35-PFT-2022-S.3(2)(10)-TH dated 8 April 2022, effective
1 April 2022 — the Gujarat Commercial Tax Department's own site was
unreachable from this environment, connection refused). The superseded
pre-2022 slab is seeded too, specifically so a rate lookup for a past date
has a real, different answer to return — not filler data.

Run directly: `python -m app.db.seed.pt_slabs`
Or import `seed_pt_slabs(db)` and call it — idempotent (upsert by
state + effective_from), safe to run repeatedly.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.modules.payroll.models import PtSlab

_CURRENT_NOTE = (
    "Gujarat notification GHN-35-PFT-2022-S.3(2)(10)-TH, dated 8 April 2022, effective "
    "1 April 2022. Verified 2026-09-03 via a tax-law publisher (TaxGuru) quoting the "
    "notification number and date; commercialtax.gujarat.gov.in itself was unreachable "
    "from this environment (connection refused) — cross-checked against three "
    "independent payroll-compliance publishers, all agreeing."
)

# The structure GHN-35-PFT-2022 replaced. Its END date (31 March 2022, the
# day before the new rate took effect) is solid — the notification that set
# it is not independently verified, so its START date below (1 Jan 2000) is
# a deliberately round, unverified placeholder: old enough to be safely
# "before" for a past-date lookup test, never presented as a real
# confirmed date. Do not treat effective_from on these two rows as checked.
_SUPERSEDED_NOTE = (
    "The structure Gujarat notification GHN-35-PFT-2022 replaced (Nil/₹80/₹150/₹200 at "
    "₹6,000/₹9,000/₹12,000 breakpoints), confirmed superseded effective 1 April 2022. "
    "Its own start date was NOT independently verified — 1 Jan 2000 here is a "
    "deliberately unverified placeholder, present only so a payroll date before "
    "1 April 2022 has a real historical rate to resolve to, not a lookup miss."
)

_OLD_START = date(2000, 1, 1)
_OLD_END = date(2022, 3, 31)
_NEW_START = date(2022, 4, 1)

GUJARAT_SLABS: list[dict] = [
    # Superseded structure (effective_to 2022-03-31) — unverified start date.
    {
        "income_min": Decimal("0.00"),
        "income_max": Decimal("5999.99"),
        "monthly_amount": Decimal("0.00"),
        "effective_from": _OLD_START,
        "effective_to": _OLD_END,
        "source_note": _SUPERSEDED_NOTE,
    },
    {
        "income_min": Decimal("6000.00"),
        "income_max": Decimal("8999.99"),
        "monthly_amount": Decimal("80.00"),
        "effective_from": _OLD_START,
        "effective_to": _OLD_END,
        "source_note": _SUPERSEDED_NOTE,
    },
    {
        "income_min": Decimal("9000.00"),
        "income_max": Decimal("11999.99"),
        "monthly_amount": Decimal("150.00"),
        "effective_from": _OLD_START,
        "effective_to": _OLD_END,
        "source_note": _SUPERSEDED_NOTE,
    },
    {
        "income_min": Decimal("12000.00"),
        "income_max": None,
        "monthly_amount": Decimal("200.00"),
        "effective_from": _OLD_START,
        "effective_to": _OLD_END,
        "source_note": _SUPERSEDED_NOTE,
    },
    # Current structure, verified.
    {
        "income_min": Decimal("0.00"),
        "income_max": Decimal("12000.00"),
        "monthly_amount": Decimal("0.00"),
        "effective_from": _NEW_START,
        "effective_to": None,
        "source_note": _CURRENT_NOTE,
    },
    {
        "income_min": Decimal("12000.01"),
        "income_max": None,
        "monthly_amount": Decimal("200.00"),
        "effective_from": _NEW_START,
        "effective_to": None,
        "source_note": _CURRENT_NOTE,
    },
]


def seed_pt_slabs(db: Session) -> None:
    """Idempotent — upsert by (state, income_min, effective_from), safe to
    re-run."""
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
            existing.source_note = row["source_note"]
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_pt_slabs(session)
        print(f"Seeded {len(GUJARAT_SLABS)} pt_slabs rows (Gujarat).")
