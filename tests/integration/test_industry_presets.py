"""WP-14: GET /industry-presets — public, no auth, no RLS (industry_presets
is global seed data, Spec 7.8). Names only, not departments_json/
leave_types_json, since the company-registration page has no use for
either before a company exists.
"""


def test_industry_presets_are_public_and_names_only(client):
    resp = client.get("/api/v1/industry-presets")
    assert resp.status_code == 200, resp.text

    names = resp.json()
    assert isinstance(names, list)
    assert all(isinstance(name, str) for name in names)
    # Matches app/db/seed/industry_presets.py's 12 seeded industries.
    assert {"Technology", "Healthcare", "Retail"} <= set(names)
    assert len(names) >= 12

    # Names only — nothing that looks like the full preset payload leaked in.
    assert all("departments_json" not in name and "leave_types_json" not in name for name in names)
