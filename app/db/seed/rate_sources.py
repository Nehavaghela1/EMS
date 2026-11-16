"""Seed: the government pages the daily rate check reads (5.9).

Idempotent: a row is looked up by (country, state, scheme group, link) and created only when
it is missing; an existing row is never touched, so a super admin's changes and the check's
runtime fields (last result, stored hash, active flag) survive a re-run. Nothing is fetched at
seed time and no rate is written. Every link must pass the government allow-list.

Some links name a tax year (the GB page); the super admin updates the link when it changes.
"""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.official_sources import is_official_url
from app.db.session import SessionLocal
from app.modules.platform.models import RateSource

SOURCE_ROWS: list[dict[str, Any]] = [
    {
        "country": "IN",
        "scheme_group": "epf_esi",
        "title": "ESIC contribution rates",
        "source_url": "https://web.esic.gov.in/web/esic/contribution",
        "interval_months": 6,
        "next_check_on": date(2026, 11, 20),
    },
    {
        "country": "GB",
        "scheme_group": "income_tax",
        "title": "HMRC rates and thresholds for employers",
        "source_url": "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027",
        "interval_months": 12,
        "next_check_on": date(2027, 3, 6),
    },
    {
        "country": "SG",
        "scheme_group": "social_security",
        "title": "CPF contribution rate changes for senior workers",
        "source_url": (
            "https://www.cpf.gov.sg/service/article/what-are-the-changes-to-the-cpf-contribution-"
            "rates-for-senior-workers-that-will-take-effect-from-1-january-2027"
        ),
        "interval_months": 12,
        "next_check_on": date(2026, 12, 1),
    },
    {
        "country": "CA",
        "scheme_group": "social_security",
        "title": "CRA CPP contribution rates and maximums",
        "source_url": (
            "https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/"
            "payroll-deductions-contributions/canada-pension-plan-cpp/"
            "cpp-contribution-rates-maximums-exemptions.html"
        ),
        "interval_months": 12,
        "next_check_on": date(2026, 12, 1),
    },
    {
        "country": "CA",
        "scheme_group": "social_security",
        "title": "ESDC EI premium rates for 2027",
        "source_url": (
            "https://www.canada.ca/en/employment-social-development/programs/ei/ei-list/reports/"
            "premium/rates2027.html"
        ),
        "interval_months": 12,
        "next_check_on": date(2026, 12, 1),
    },
    {
        "country": "AU",
        "scheme_group": "social_security",
        "title": "ATO super guarantee rate",
        "source_url": (
            "https://www.ato.gov.au/tax-rates-and-codes/key-superannuation-rates-and-thresholds/"
            "super-guarantee"
        ),
        "interval_months": 12,
        "next_check_on": date(2027, 6, 1),
    },
    {
        "country": "US",
        "scheme_group": "social_security",
        "title": "SSA 2026 COLA and wage base fact sheet",
        "source_url": "https://www.ssa.gov/cola/factsheets/2026.html",
        "interval_months": 12,
        "next_check_on": date(2026, 12, 1),
    },
    {
        "country": "AE",
        "scheme_group": "other",
        "title": "Dubai unemployment insurance (ILOE)",
        "source_url": "https://www.dubai.ae/living/jobs-employment/involuntary-loss-of-employment",
        "interval_months": 6,
        "next_check_on": date(2027, 5, 5),
    },
]


def seed_rate_sources(db: Session) -> None:
    for row in SOURCE_ROWS:
        if not is_official_url(row["source_url"]):
            raise ValueError(f"A seeded rate source is not on the official list: {row['title']}")
    for row in SOURCE_ROWS:
        existing = (
            db.query(RateSource)
            .filter(
                RateSource.country == row["country"],
                RateSource.state.is_(None),
                RateSource.scheme_group == row["scheme_group"],
                RateSource.source_url == row["source_url"],
                RateSource.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            db.add(RateSource(state=None, active=True, last_result="never", **row))
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_rate_sources(session)
        print(f"Seeded {len(SOURCE_ROWS)} rate_sources rows.")
