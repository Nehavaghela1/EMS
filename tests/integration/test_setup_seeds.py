"""scripts/setup.sh must leave a database that can run payroll (CI and every new setup use it).

A fresh database used to hold only `industry_presets`, so every payroll run returned 409 (no PF,
ESI, professional-tax or income-tax row in force). The three rate seeds are now steps of setup.sh,
and together they cover every month from April 2025 to March 2027.
"""

import re
from calendar import monthrange
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.db.seed.pt_slabs import seed_pt_slabs
from app.db.seed.statutory_rates import seed_statutory_rates
from app.db.seed.tax_slabs import seed_tax_slabs
from app.modules.payroll.models import TaxRegime
from app.modules.payroll.repository import (
    PtSlabRepository,
    StatutoryRateRepository,
    TaxSlabRepository,
)
from tests.conftest import REPO_ROOT

SETUP = REPO_ROOT / "scripts" / "setup.sh"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def test_setup_sh_runs_the_three_rate_seeds_right_after_industry_presets() -> None:
    text = SETUP.read_text()
    steps = [
        m.start()
        for m in (
            re.search(rf"python3 -m app\.db\.seed\.{name}\b", text)
            for name in ("industry_presets", "statutory_rates", "pt_slabs", "tax_slabs")
        )
        if m is not None
    ]
    assert len(steps) == 4, (
        "setup.sh must run industry_presets, statutory_rates, pt_slabs, tax_slabs"
    )
    assert steps == sorted(steps), "the three rate seeds come after industry_presets, in order"
    for name in ("statutory_rates", "pt_slabs", "tax_slabs"):
        line = next(seg for seg in text.split("\n\n") if f"app.db.seed.{name}" in seg)
        assert "ems_app:" in line and "DATABASE_URL" in line, (
            f"{name} must run as the runtime role against the database just migrated"
        )
        assert "|| fail" in line, f"{name} must stop setup.sh when it fails"


def test_claude_md_says_production_runs_the_setup_steps_and_when_a_new_tax_year_is_due() -> None:
    text = CLAUDE_MD.read_text()
    assert "setup.sh" in text and "1 April" in text, (
        "CLAUDE.md must say production runs the setup.sh steps after every release and that a "
        "new tax year needs a new tax set before 1 April"
    )


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[date]:
    out, (year, month) = [], start
    while (year, month) <= end:
        out.append(date(year, month, 1))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def _seed_all(db: Session) -> None:
    seed_pt_slabs(db)
    seed_tax_slabs(db)
    seed_statutory_rates(db)


def _what_is_missing(db: Session, first_day: date) -> list[str]:
    missing = []
    rates = StatutoryRateRepository(db)
    if rates.get_in_force("IN", "epf", first_day) is None:
        missing.append("PF")
    if rates.get_in_force("IN", "esi", first_day) is None:
        missing.append("ESI")
    if not PtSlabRepository(db).list_for_state("IN", "Gujarat", on_date=first_day):
        missing.append("PT")
    year = first_day.year if first_day.month >= 4 else first_day.year - 1
    fy = f"{year}-{year + 1}"
    for regime in (TaxRegime.new, TaxRegime.old):
        if not TaxSlabRepository(db).list_in_force("IN", fy, regime, first_day):
            missing.append(f"tax {regime.value}")
    return missing


@pytest.mark.parametrize("first_day", [date(2026, 9, 1), date(2026, 10, 1), date(2027, 3, 1)])
def test_the_seeds_leave_a_pf_esi_pt_and_tax_row_in_force(db: Session, first_day: date) -> None:
    _seed_all(db)
    assert _what_is_missing(db, first_day) == [], f"nothing in force for {first_day:%Y-%m}"


def test_the_seeds_cover_every_month_from_april_2025_to_march_2027(db: Session) -> None:
    _seed_all(db)
    gaps = {
        f"{d:%Y-%m}": missing
        for d in _months((2025, 4), (2027, 3))
        if (missing := _what_is_missing(db, d))
    }
    assert gaps == {}, f"months a payroll run could not use: {gaps}"
    assert monthrange(2027, 3)[1] == 31


def test_seeding_again_changes_nothing(db: Session) -> None:
    _seed_all(db)
    before = _what_is_missing(db, date(2026, 10, 1))
    _seed_all(db)
    assert before == _what_is_missing(db, date(2026, 10, 1)) == []
