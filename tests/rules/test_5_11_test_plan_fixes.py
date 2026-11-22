# ruff: noqa: F401, F811  (pytest fixtures imported from a sibling test module)
"""Module 5 fixes for problems found by the end-to-end test plan (21-Nov-2026).

BUG-052  a payroll run request without an Idempotency-Key gets the standard error envelope
"""

from tests.rules.test_5_4_payroll_runs import RUNS, _structure, world


def test_missing_idempotency_key_uses_the_error_envelope(client, db, world) -> None:
    resp = client.post(
        RUNS, json={"month": world["month"], "year": world["year"]}, headers=world["hr1"]
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" not in body
    assert body["error"]["code"] == "idempotency_key_required"
    assert body["error"]["message"] == "Idempotency-Key header is required."
    assert body["error"]["request_id"]


# --- BUG-101 (payroll tables only): a stale edit cannot overwrite a newer one -------------

STRUCTURES = "/api/v1/payroll/structures"


def test_a_stale_salary_structure_edit_is_refused(client, db, world) -> None:
    """Two tabs, one structure. The second save used to win silently and wipe
    out the first; it is now refused and the person is told to reload."""
    hr = world["hr1"]
    structure_id = world["structure_id"]

    # Both tabs read the same edition.
    first_read = client.get(f"{STRUCTURES}/{structure_id}", headers=hr)
    assert first_read.status_code == 200, first_read.text
    opened_version = first_read.json()["version"]

    # Tab 1 saves. The edition moves on, and the structure records who did it.
    tab_one = client.put(
        f"{STRUCTURES}/{structure_id}",
        headers=hr,
        json={"level": "L2", "version": opened_version},
    )
    assert tab_one.status_code == 200, tab_one.text
    assert tab_one.json()["version"] == opened_version + 1
    assert tab_one.json()["updated_by_email"]

    # Tab 2 still holds the edition it opened, so its save is refused.
    tab_two = client.put(
        f"{STRUCTURES}/{structure_id}",
        headers=hr,
        json={"name": "Renamed by the stale tab", "version": opened_version},
    )
    assert tab_two.status_code == 409, tab_two.text
    assert "changed by someone else" in tab_two.json()["error"]["message"]

    # Tab 1's change survived and nothing of tab 2's was written.
    after = client.get(f"{STRUCTURES}/{structure_id}", headers=hr).json()
    assert after["level"] == "L2"
    assert after["name"] != "Renamed by the stale tab"
    assert after["version"] == opened_version + 1


def test_a_reloaded_edit_goes_through(client, db, world) -> None:
    """The conflict is not a dead end: reload, re-apply, save."""
    hr = world["hr1"]
    structure_id = world["structure_id"]

    current = client.get(f"{STRUCTURES}/{structure_id}", headers=hr).json()
    resp = client.put(
        f"{STRUCTURES}/{structure_id}",
        headers=hr,
        json={"level": "L3", "version": current["version"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["level"] == "L3"


def test_a_structure_records_who_made_it(client, db, world) -> None:
    """'Who changed this' lived only in the audit log before (BUG-101 follow-up)."""
    structure_id = _structure(client, world["hr1"])
    created = client.get(f"{STRUCTURES}/{structure_id}", headers=world["hr1"])
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["version"] == 1
    assert body["created_by_email"]
    assert body["created_by_email"] == body["updated_by_email"]
