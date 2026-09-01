"""Seeds the `industry_presets` table (Spec 7.8) — 12 industries, applied
automatically when a company is approved (WP-05: departments now;
leave types once `leave_types` exists, WP-10).

Run directly: `python -m app.db.seed.industry_presets`
Or import `seed_industry_presets(db)` and call it — idempotent (upsert by
`industry_name`), safe to run repeatedly.
"""

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.modules.platform.models import IndustryPreset

# A common baseline leave policy. Real per-industry variation (e.g. more paid
# sick leave in healthcare) is a product decision for whoever finalizes this
# before WP-10 actually applies it — this is a structurally reasonable
# starting point, not verified against any specific company's policy.
_STANDARD_LEAVE_TYPES = [
    {
        "name": "Annual Leave",
        "code": "annual",
        "annual_allowance": 18,
        "carry_forward_limit": 6,
        "max_consecutive_days": 15,
        "is_paid": True,
        "is_encashable": True,
    },
    {
        "name": "Sick Leave",
        "code": "sick",
        "annual_allowance": 10,
        "carry_forward_limit": 0,
        "max_consecutive_days": None,
        "is_paid": True,
        "is_encashable": False,
    },
    {
        "name": "Casual Leave",
        "code": "casual",
        "annual_allowance": 8,
        "carry_forward_limit": 0,
        "max_consecutive_days": 3,
        "is_paid": True,
        "is_encashable": False,
    },
    {
        "name": "Maternity Leave",
        "code": "maternity",
        "annual_allowance": 182,
        "carry_forward_limit": 0,
        "max_consecutive_days": None,
        "is_paid": True,
        "is_encashable": False,
    },
    {
        "name": "Paternity Leave",
        "code": "paternity",
        "annual_allowance": 15,
        "carry_forward_limit": 0,
        "max_consecutive_days": None,
        "is_paid": True,
        "is_encashable": False,
    },
]


def _departments(*names: str) -> list[dict]:
    return [{"name": name} for name in names]


INDUSTRY_PRESETS: list[dict] = [
    {
        "industry_name": "Technology",
        "departments_json": _departments(
            "Engineering",
            "Product",
            "Design",
            "Quality Assurance",
            "DevOps",
            "Sales",
            "Human Resources",
        ),
    },
    {
        "industry_name": "Manufacturing",
        "departments_json": _departments(
            "Production",
            "Quality Control",
            "Supply Chain",
            "Maintenance",
            "Sales",
            "Human Resources",
        ),
    },
    {
        "industry_name": "Healthcare",
        "departments_json": _departments(
            "Clinical Operations",
            "Nursing",
            "Pharmacy",
            "Administration",
            "Billing",
            "Human Resources",
        ),
    },
    {
        "industry_name": "Retail",
        "departments_json": _departments(
            "Store Operations",
            "Merchandising",
            "Supply Chain",
            "Marketing",
            "Customer Service",
            "Human Resources",
        ),
    },
    {
        "industry_name": "Banking & Financial Services",
        "departments_json": _departments(
            "Retail Banking", "Risk & Compliance", "Operations", "Finance", "IT", "Human Resources"
        ),
    },
    {
        "industry_name": "Education",
        "departments_json": _departments(
            "Academics", "Admissions", "Student Affairs", "Administration", "IT", "Human Resources"
        ),
    },
    {
        "industry_name": "Hospitality",
        "departments_json": _departments(
            "Front Office",
            "Housekeeping",
            "Food & Beverage",
            "Sales & Marketing",
            "Human Resources",
        ),
    },
    {
        "industry_name": "Construction",
        "departments_json": _departments(
            "Project Management",
            "Site Operations",
            "Procurement",
            "Safety & Compliance",
            "Human Resources",
        ),
    },
    {
        "industry_name": "Real Estate",
        "departments_json": _departments(
            "Sales", "Leasing", "Property Management", "Legal", "Finance", "Human Resources"
        ),
    },
    {
        "industry_name": "Logistics & Transportation",
        "departments_json": _departments(
            "Fleet Operations", "Warehousing", "Dispatch", "Customer Service", "Human Resources"
        ),
    },
    {
        "industry_name": "Media & Entertainment",
        "departments_json": _departments(
            "Content", "Production", "Marketing", "Distribution", "Human Resources"
        ),
    },
    {
        "industry_name": "Non-Profit",
        "departments_json": _departments(
            "Programs",
            "Fundraising",
            "Communications",
            "Finance & Administration",
            "Human Resources",
        ),
    },
]


def seed_industry_presets(db: Session) -> None:
    """Idempotent — insert-or-update by `industry_name`, safe to re-run."""
    for preset in INDUSTRY_PRESETS:
        existing = db.query(IndustryPreset).filter_by(industry_name=preset["industry_name"]).first()
        if existing is None:
            db.add(
                IndustryPreset(
                    industry_name=preset["industry_name"],
                    departments_json=preset["departments_json"],
                    leave_types_json=_STANDARD_LEAVE_TYPES,
                )
            )
        else:
            existing.departments_json = preset["departments_json"]
            existing.leave_types_json = _STANDARD_LEAVE_TYPES
    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed_industry_presets(session)
        print(f"Seeded {len(INDUSTRY_PRESETS)} industry presets.")
