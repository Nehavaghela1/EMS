from pathlib import Path


def test_no_local_date_today_or_utcnow_in_app():
    """B2 & Z3 guard test: Ensure app/ uses the UTC helpers (utcnow().date() and utcnow())
    and never local date.today() or deprecated datetime.utcnow().
    """
    root = Path(__file__).resolve().parents[2] / "app"
    assert root.exists() and root.is_dir(), f"App directory not found: {root}"

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
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            rel = py_file.relative_to(root.parent)
            if "date.today()" in line:
                violations.append(f"{rel}:{line_no}: forbidden date.today() -> {line}")
            if "datetime.utcnow()" in line:
                violations.append(f"{rel}:{line_no}: forbidden datetime.utcnow() -> {line}")

    msg = "Found forbidden date.today() or datetime.utcnow() in app/:\n" + "\n".join(violations)
    assert not violations, msg


def test_no_local_date_today_in_tests():
    """Ensure tests/ uses utcnow().date() and never local date.today()."""
    root = Path(__file__).resolve().parents[1]
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
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            rel = py_file.relative_to(root.parent)
            if "date.today()" in line:
                violations.append(f"{rel}:{line_no}: forbidden date.today() -> {line}")

    msg = "Found forbidden date.today() in tests/:\n" + "\n".join(violations)
    assert not violations, msg
