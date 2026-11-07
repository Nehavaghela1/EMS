"""The one list of countries and their states or regions.

A country or state is always CHOSEN from this list, never typed: company registration, the
professional-tax state, the statutory-rate write routes and the holiday import all read it.
Spelling is canonical here; `canonical_state` matches an input to it, ignoring case and
surrounding spaces.
"""

from typing import Any

COUNTRY_REGIONS_MAP: dict[str, dict[str, Any]] = {
    "IN": {
        "name": "India",
        "states": [
            # 28 States
            "Andhra Pradesh",
            "Arunachal Pradesh",
            "Assam",
            "Bihar",
            "Chhattisgarh",
            "Goa",
            "Gujarat",
            "Haryana",
            "Himachal Pradesh",
            "Jharkhand",
            "Karnataka",
            "Kerala",
            "Madhya Pradesh",
            "Maharashtra",
            "Manipur",
            "Meghalaya",
            "Mizoram",
            "Nagaland",
            "Odisha",
            "Punjab",
            "Rajasthan",
            "Sikkim",
            "Tamil Nadu",
            "Telangana",
            "Tripura",
            "Uttar Pradesh",
            "Uttarakhand",
            "West Bengal",
            # 8 Union Territories
            "Andaman and Nicobar Islands",
            "Chandigarh",
            "Dadra and Nagar Haveli and Daman and Diu",
            "Delhi (NCT)",
            "Jammu and Kashmir",
            "Ladakh",
            "Lakshadweep",
            "Puducherry",
        ],
    },
    "US": {
        "name": "United States",
        "states": [
            "Alabama",
            "Alaska",
            "Arizona",
            "Arkansas",
            "California",
            "Colorado",
            "Connecticut",
            "Delaware",
            "District of Columbia",
            "Florida",
            "Georgia",
            "Hawaii",
            "Idaho",
            "Illinois",
            "Indiana",
            "Iowa",
            "Kansas",
            "Kentucky",
            "Louisiana",
            "Maine",
            "Maryland",
            "Massachusetts",
            "Michigan",
            "Minnesota",
            "Mississippi",
            "Missouri",
            "Montana",
            "Nebraska",
            "Nevada",
            "New Hampshire",
            "New Jersey",
            "New Mexico",
            "New York",
            "North Carolina",
            "North Dakota",
            "Ohio",
            "Oklahoma",
            "Oregon",
            "Pennsylvania",
            "Rhode Island",
            "South Carolina",
            "South Dakota",
            "Tennessee",
            "Texas",
            "Utah",
            "Vermont",
            "Virginia",
            "Washington",
            "West Virginia",
            "Wisconsin",
            "Wyoming",
        ],
    },
    "GB": {
        "name": "United Kingdom",
        "states": [
            "England",
            "Scotland",
            "Wales",
            "Northern Ireland",
        ],
    },
    "AE": {
        "name": "United Arab Emirates",
        "states": [
            "Abu Dhabi",
            "Dubai",
            "Sharjah",
            "Ajman",
            "Umm Al Quwain",
            "Ras Al Khaimah",
            "Fujairah",
        ],
    },
    "SG": {
        "name": "Singapore",
        "states": [
            "Central Region",
            "East Region",
            "North Region",
            "North-East Region",
            "West Region",
            "National (All Singapore)",
        ],
    },
    "CA": {
        "name": "Canada",
        "states": [
            # 10 Provinces
            "Alberta",
            "British Columbia",
            "Manitoba",
            "New Brunswick",
            "Newfoundland and Labrador",
            "Nova Scotia",
            "Ontario",
            "Prince Edward Island",
            "Quebec",
            "Saskatchewan",
            # 3 Territories
            "Northwest Territories",
            "Nunavut",
            "Yukon",
        ],
    },
    "AU": {
        "name": "Australia",
        "states": [
            # 6 States
            "New South Wales",
            "Queensland",
            "South Australia",
            "Tasmania",
            "Victoria",
            "Western Australia",
            # 2 Internal Territories
            "Australian Capital Territory",
            "Northern Territory",
        ],
    },
}

# A country is added here only when its statutory tables (statutory_rates, pt_slabs, tax_slabs)
# hold rows with official sources. Every other country can be chosen for a company, but a
# payroll run or employee bank details for it are refused until it is ready.
PAYROLL_READY_COUNTRIES: frozenset[str] = frozenset({"IN"})


DEFAULT_COUNTRY = "IN"


def allowed_country_codes() -> str:
    """The codes, sorted and comma-separated, for an error message."""
    return ", ".join(sorted(COUNTRY_REGIONS_MAP))


def canonical_country(value: str | None) -> str | None:
    """The upper-case code when `value` is a listed country (case and spaces ignored), else None."""
    code = (value or "").strip().upper()
    return code if code in COUNTRY_REGIONS_MAP else None


def country_name(code: str) -> str:
    entry = COUNTRY_REGIONS_MAP.get(code)
    return entry["name"] if entry else code


def is_payroll_ready(code: str) -> bool:
    return code in PAYROLL_READY_COUNTRIES


def canonical_state(country: str, value: str | None) -> str | None:
    """The canonical spelling of `value` among the states of `country`, else None."""
    entry = COUNTRY_REGIONS_MAP.get(country)
    if entry is None:
        return None
    wanted = (value or "").strip().lower()
    return next((s for s in entry["states"] if s.lower() == wanted), None)
