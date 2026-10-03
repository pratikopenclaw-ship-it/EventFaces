"""Forced updates: app requests below IOS_MIN_SUPPORTED_VERSION (or without a version) get
426 before anything else runs; the browser is never affected."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models import User


@pytest.fixture(autouse=True)
def _minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ios_min_supported_version", "1.4.0")


def _app(version: str | None, bearer: str = "x") -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {bearer}"
    if version is not None:
        c.headers["X-App-Version"] = version
    return c


@pytest.mark.parametrize("version", [None, "", "1.3.9", "0.9.99", "1.4", "v1.4.0", "1.4.0-beta", "1.4.0.1", "99999.0.0"])
def test_outdated_or_missing_versions_must_update(version: str | None) -> None:
    r = _app(version).get("/api/me")
    assert r.status_code == 426
    assert r.json() == {"detail": "update_required", "min_supported_version": "1.4.0", "update_url": get_settings().ios_update_url}


@pytest.mark.parametrize("version", ["1.4.0", "1.4.1", "1.10.0", "2.0.0"])
def test_supported_versions_pass_the_gate(version: str) -> None:
    assert _app(version).get("/api/me").status_code == 401  # reached auth: the token is fake


def test_the_gate_runs_before_sign_in_endpoints() -> None:
    c = TestClient(app)
    c.headers["X-App-Version"] = "1.0.0"
    assert c.post("/api/mobile/auth/code/request", json={"email": "old@example.com"}).status_code == 426


def test_config_is_reachable_by_outdated_apps() -> None:
    r = _app("0.1.0").get("/api/app/config?platform=ios")
    assert r.status_code == 200 and r.json()["min_supported_version"] == "1.4.0"


def test_browsers_are_unaffected(make_user: Callable[..., User], login_as: Callable[..., TestClient]) -> None:
    assert login_as(make_user("browser@example.com")).get("/api/me").status_code == 200
