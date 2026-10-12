import subprocess
import sys


def test_project_document_create_mypy_typecheck():
    """Verify that ProjectDocumentCreate in projects/router.py typechecks cleanly with mypy.

    Without file_name explicitly passed to ProjectDocumentCreate in add_project_document,
    mypy's pydantic plugin fails with:
      error: Missing named argument "file_name" for "ProjectDocumentCreate" [call-arg]
    """
    cmd = [
        sys.executable,
        "-m",
        "mypy",
        "app/modules/projects/router.py",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"mypy typecheck failed:\n{res.stdout}\n{res.stderr}"
