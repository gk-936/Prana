import os
import subprocess
import sys


def _lint_imports_command():
    """
    Build the command to invoke import-linter under the same interpreter
    pytest is running with.

    `python -m importlinter` does not work: the installed `importlinter`
    package has no `__main__.py`, so `-m importlinter` fails with
    "No module named importlinter.__main__". `python -m importlinter.cli`
    is also unusable as a check: it imports the module (which only
    *defines* the click command, never calls it) and always exits 0
    regardless of arguments or config validity, so it can't actually
    detect a failing contract.

    The real, working entry point is the `lint-imports` console script
    installed alongside the interpreter (e.g. `.venv/Scripts/lint-imports.exe`
    on Windows, `.venv/bin/lint-imports` on POSIX). Resolving it relative to
    `sys.executable` keeps this test pinned to whatever interpreter/venv
    pytest itself is running under.
    """
    scripts_dir = os.path.dirname(sys.executable)
    exe_name = "lint-imports.exe" if os.name == "nt" else "lint-imports"
    lint_imports_path = os.path.join(scripts_dir, exe_name)
    assert os.path.exists(lint_imports_path), (
        f"lint-imports console script not found at {lint_imports_path}; "
        "is import-linter installed in this environment?"
    )
    return [lint_imports_path, "--config", ".importlinter"]


def test_framework_does_not_import_prana_or_backend():
    result = subprocess.run(
        _lint_imports_command(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
