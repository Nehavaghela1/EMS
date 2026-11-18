from pathlib import Path


def test_no_local_date_today_in_app_modules():
    """B2 guard test: Ensure app/modules/ uses the UTC date helper (utcnow().date())
    and never local date.today().
    """
    root = Path(__file__).resolve().parents[2] / "app" / "modules"
    assert root.exists() and root.is_dir(), f"Modules directory not found: {root}"

    violations: list[str] = []
    this_file = Path(__file__).resolve()

    for py_file in root.rglob("*.py"):
        if py_file.resolve() == this_file:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            # Fail if date.today() appears in code
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "date.today()" in line:
                violations.append(f"{py_file.relative_to(root.parent.parent)}:{line_no}: {line}")

    assert not violations, "Found forbidden local date.today() in app/modules/:\n" + "\n".join(
        violations
    )
