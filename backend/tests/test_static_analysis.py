"""Static-analysis gates run as part of the test suite, so a reintroduced finding fails CI.

Config: ruff.toml (lint + flake8-bandit security rules), mypy.ini (strict on auth/authz
modules), bandit over app/ at every severity. Exceptions are inline `noqa`/`nosec` with a
written justification (see SECURITY_QA_REPORT.md).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _run(*cmd: str) -> subprocess.CompletedProcess[str]:
    if shutil.which(cmd[0]) is None:
        pytest.skip(f"{cmd[0]} not installed (dev image only)")
    return subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=600, check=False)  # noqa: S603 - fixed tool argv from this file


def test_ruff_clean() -> None:
    r = _run("ruff", "check", ".", "--output-format", "concise")  # app, tests, scripts, migrations
    assert r.returncode == 0, r.stdout + r.stderr


def test_mypy_clean() -> None:
    r = _run("mypy", "app")
    assert r.returncode == 0, r.stdout + r.stderr


def test_bandit_clean() -> None:
    r = _run("bandit", "-r", "app", "-q", "-f", "txt")
    assert r.returncode == 0, r.stdout + r.stderr
