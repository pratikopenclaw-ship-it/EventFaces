"""Per-endpoint contract tests (Phase C), driven by the authorization matrix's operation
table so every endpoint is covered: malformed bodies → 422, unknown IDs → 404, and every
rate-limited endpoint really returns 429 once its budget is spent.

(Success/401/403 per endpoint and role: tests/test_authz_matrix.py. Conflicts: the
concurrency, upload, invite and join tests.)"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.config import get_settings
from app.main import app
from tests.conftest import PASSWORD, new_client
from tests.test_authz_matrix import OPS, Op, World, _client, _fill, world  # noqa: F401  (fixture re-export)

# Schemas whose fields are all optional: {} is a valid (no-op) update.
ALL_OPTIONAL = {
    ("PATCH", "/api/events/{event_a}"),
    ("PATCH", "/api/events/{event_a}/members/{member_a}"),
    ("DELETE", "/api/me"),  # password or code: {} is well-formed (and then refused with 403)
    ("PATCH", "/api/me/preferences"),  # each preference is optional; {} changes nothing
}

# Every endpoint that enforces a rate limit (see `rate_limit.enforce` call sites).
RATE_LIMITED = {
    ("POST", "/api/contact"),
    ("POST", "/api/alerts/unsubscribe"),
    ("POST", "/api/billing/checkout"),
    ("POST", "/api/events/{event_a}/addons/checkout"),
    ("POST", "/api/billing/addon-checkout/fcs_not-a-session/pay"),
    ("POST", "/api/billing/test-checkout/fcs_not-a-session/pay"),
    ("POST", "/api/billing/subscription/events"),
    ("POST", "/api/billing/webhook/fake"),
    ("POST", "/api/auth/signup"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/resend-verification"),
    ("POST", "/api/auth/forgot-password"),
    ("GET", "/api/invites/not-a-real-token-123"),
    ("POST", "/api/invites/accept"),
    ("POST", "/api/invites/register"),
    ("POST", "/api/removal-requests"),
    ("GET", "/api/removal-requests/event/{slug_a}"),
    ("POST", "/api/removal-requests/not-a-real-token-123/submit"),
    ("DELETE", "/api/me"),
    ("GET", "/api/join/{slug_a}"),
    ("POST", "/api/join"),
    ("POST", "/api/join/by-code"),
    ("GET", "/api/downloads/not-a-real-token"),
    ("POST", "/api/events/{event_a}/capture-token"),
    ("POST", "/api/events/{event_a}/search?source=upload"),
    ("POST", "/api/events/{event_a}/downloads"),
    ("POST", "/api/events/{event_a}/feedback"),
    ("POST", "/api/events/{event_a}/feedback/missing"),
    ("POST", "/api/events/{event_a}/photos/{photo_a}/report"),
    ("POST", "/api/events/{event_a}/uploads"),
    ("POST", "/api/events/{event_a}/invites"),
    ("POST", "/api/events/{event_a}/invites/{invite_a}/resend"),
    ("POST", "/api/events/{event_a}/sync"),
    ("POST", "/api/me/reauth-code"),
    ("POST", "/api/mobile/auth/code/request"),
    ("POST", "/api/mobile/auth/code/verify"),
    ("POST", "/api/mobile/auth/magic"),
    ("POST", "/api/mobile/auth/refresh"),
    ("POST", "/api/me/devices/current/attest/challenge"),
}

ID_PLACEHOLDERS = ("{photo_a}", "{invite_a}", "{report_a}", "{removal_a}", "{member_a}", "{event_a}")


def _app() -> TestClient:
    """The iOS app's pre-login client (no cookies, version header)."""
    c = TestClient(app)
    c.headers["X-App-Version"] = "1.0.0"
    return c


def _admin(op: Op | None = None) -> TestClient:
    if op is not None and op.transports == ("bearer",):
        return _app()
    c = new_client()
    assert c.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD}).status_code == 200
    return c


def _call(c: TestClient, op: Op, w: World, path: str | None = None, headers: dict[str, str] | None = None, **kw: Any):  # type: ignore[no-untyped-def]
    return c.request(op.method, _fill(path or op.path, w), headers={**(op.headers or {}), **(headers or {})}, **kw)


BODY_OPS = [op for op in OPS if op.json is not None]


@pytest.mark.parametrize("op", BODY_OPS, ids=lambda o: f"{o.method} {o.path}")
def test_malformed_json_is_422(op: Op, world: World) -> None:  # noqa: F811
    c = _admin(op)
    r = _call(c, op, world, content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text[:200]
    r = _call(c, op, world, json=["a", "list"])
    assert r.status_code == 422, r.text[:200]


@pytest.mark.parametrize("op", [o for o in BODY_OPS if (o.method, o.path) not in ALL_OPTIONAL], ids=lambda o: f"{o.method} {o.path}")
def test_missing_required_fields_is_422(op: Op, world: World) -> None:  # noqa: F811
    r = _call(_admin(op), op, world, json={})
    assert r.status_code == 422, r.text[:200]


@pytest.mark.parametrize("op", BODY_OPS, ids=lambda o: f"{o.method} {o.path}")
def test_wrong_types_are_422(op: Op, world: World) -> None:  # noqa: F811
    body = {k: {"$gt": ""} for k in op.json}  # objects where scalars/lists are expected
    if not body:
        pytest.skip("no fields")  # justified: nothing to mistype
    r = _call(_admin(op), op, world, json=body)
    assert r.status_code == 422, r.text[:200]


ID_OPS = [(op, ph) for op in OPS for ph in ID_PLACEHOLDERS if ph in op.path]


@pytest.mark.parametrize(("op", "placeholder"), ID_OPS, ids=[f"{o.method} {o.path} [{p}]" for o, p in ID_OPS])
def test_unknown_ids_are_404(op: Op, placeholder: str, world: World) -> None:  # noqa: F811
    path = op.path.replace(placeholder, str(uuid.uuid4()))
    r = _call(_admin(), op, world, path=path, json=_fill(op.json, world) if op.json is not None else None, content=op.content)
    assert r.status_code == 404, (path, r.status_code, r.text[:200])


def test_rate_limited_list_matches_the_code() -> None:
    """Keeps RATE_LIMITED honest: the number of distinct enforce() call sites in routes."""
    import pathlib
    import re

    routes = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
    handlers_with_limits = 0
    for f in routes.glob("*.py"):
        for block in re.split(r"\n@\w*router\.", f.read_text())[1:]:  # router, me_router, ...
            if "rate_limit.enforce(" in block.split("\n@")[0]:
                handlers_with_limits += 1
    assert handlers_with_limits == len(RATE_LIMITED)


@pytest.mark.parametrize("op", [o for o in OPS if (o.method, o.path) in RATE_LIMITED], ids=lambda o: f"{o.method} {o.path}")
def test_rate_limited_endpoints_return_429(op: Op, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    login_as = "admin@example.com"
    if op.path.startswith("/api/events/{event_a}") and "invites" not in op.path and "sync" not in op.path:
        login_as = "member@example.com"  # member-only flows (grants, uploads) belong to the member
    if op.path == "/api/me/devices/current/attest/challenge":
        monkeypatch.setattr(get_settings(), "app_attest_app_id", "ABCDE12345.app.eventfaces.ios")
        c = _client("attendee_not_member", world, "bearer")  # app-only: needs a device session
    elif op.transports == ("bearer",):
        c = _app()
    else:
        c = new_client()
        assert c.post("/api/auth/login", json={"email": login_as, "password": PASSWORD}).status_code == 200
    monkeypatch.setattr(get_settings(), "allow_selfie_file_upload", True)

    real_enforce = rate_limit.enforce
    monkeypatch.setattr(rate_limit, "enforce", lambda key, limit: real_enforce(key, rate_limit.Limit(1, limit.seconds)))
    body = _fill(op.json, world) if op.json is not None else None
    if op.path == "/api/me":
        body = {"password": "wrong-password-x"}  # don't actually delete the account
    codes = [_call(c, op, world, json=body, content=op.content).status_code for _ in range(3)]
    assert codes[-1] == 429, codes
