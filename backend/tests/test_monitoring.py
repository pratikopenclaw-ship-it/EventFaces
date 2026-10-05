"""Error reporting (GlitchTip) never carries personal data or secrets.

Events are captured with a test transport and inspected: no request bodies (the selfie),
cookies, auth headers, query strings, tokens in URLs or messages, emails or IPs.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.core import monitoring
from app.core.config import get_settings
from app.models import Event, MemberRole, User
from app.services.search import FACE_CONSENT_VERSION
from tests.helpers import search_as


class Capture(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            if item.headers.get("type") in ("event", "transaction"):
                self.events.append(json.loads(item.payload.get_bytes()))


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[Capture]:
    transport = Capture()
    monkeypatch.setattr(get_settings(), "sentry_dsn", "http://public@glitchtip.invalid/1")
    monkeypatch.setattr(get_settings(), "sentry_traces_sample_rate", 0.0)
    assert monitoring.init("api", transport=transport)
    yield transport
    sentry_sdk.init(dsn=None)  # reporting off again for the other tests


def test_off_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "sentry_dsn", "")
    assert monitoring.init("api") is False


def test_the_sdk_never_collects_bodies_pii_or_locals(captured: Capture) -> None:
    """First line of defence: the SDK never reads these at all (`scrub` is the second)."""
    client = sentry_sdk.get_client()
    assert client.options["max_request_body_size"] == "never"
    assert client.options["send_default_pii"] is False
    assert client.options["include_local_variables"] is False
    assert client.options["before_send"] is monitoring.scrub
    assert client.options["before_send_transaction"] is monitoring.scrub


def test_scrub_removes_everything_personal() -> None:
    event = {
        "message": "failed for https://x.example/api/downloads/SECRETTOKEN123",
        "request": {
            "method": "POST",
            "url": "https://x.example/api/invites/INVITETOKEN99?token=QUERYTOKEN",
            "query_string": "token=QUERYTOKEN",
            "data": "\xff\xd8selfie-bytes",
            "cookies": {"ef_access": "jwt"},
            "headers": {"Authorization": "Bearer abc", "Cookie": "ef_access=jwt", "X-Capture-Token": "ct", "Content-Type": "image/jpeg"},
            "env": {"REMOTE_ADDR": "203.0.113.9"},
        },
        "user": {"id": "u-1", "email": "alice@example.com", "ip_address": "203.0.113.9"},
        "extra": {"body": "secret"},
        "server_name": "host-1",
        "logentry": {"message": "token=%s", "params": ["LEAK"], "formatted": "token=LEAK /removal/RMTOKEN"},
        "exception": {"values": [{"type": "RuntimeError", "value": "see /invite/INVTOKEN for carol@example.org, Bearer eyJhbGciOiFAKE", "stacktrace": {"frames": [{"function": "f", "vars": {"password": "hunter2"}}]}}]},
        "breadcrumbs": {"values": [{"category": "httplib", "message": "GET /api/downloads/DLTOKEN", "data": {"url": "https://x/path/BREADCRUMBDATA"}}]},
    }
    clean = json.dumps(monitoring.scrub(event))
    for secret in ("SECRETTOKEN123", "INVITETOKEN99", "QUERYTOKEN", "selfie-bytes", "jwt", "Bearer", "ct\"", "203.0.113.9",
                   "alice@example.com", "hunter2", "LEAK", "RMTOKEN", "INVTOKEN", "DLTOKEN", "BREADCRUMBDATA", "host-1", "secret", "carol@example.org", "eyJhbGciOiFAKE"):
        assert secret not in clean, secret
    assert '"Content-Type": "image/jpeg"' in clean  # harmless triage headers stay
    assert '"id": "u-1"' in clean


def test_a_crash_during_a_selfie_search_reports_no_personal_data(
    captured: Capture,
    monkeypatch: pytest.MonkeyPatch,
    make_user: Callable[..., User],
    make_event: Callable[..., Event],
    add_member: Callable[..., object],
    login_as: Callable[[User], TestClient],
) -> None:
    user = make_user("crash@example.com")
    event = make_event("Crash party")
    add_member(event, user, role=MemberRole.attendee)
    client = login_as(user)
    assert client.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION}).status_code == 200

    secret = "LEAKED" + "TOKEN"  # built at run time: error reports include source lines as context

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(f"matcher failed for /api/downloads/{secret} token={secret} user={user.email}")

    monkeypatch.setattr("app.api.routes.search.run_search", boom)
    with pytest.raises(RuntimeError):
        search_as(client, event)
    assert captured.events, "the crash is reported"
    payload = json.dumps(captured.events)
    assert "RuntimeError" in payload
    # Values, not words: error reports include our own source lines as context.
    session_values = [v for v in client.cookies.values() if len(v) > 8]
    assert session_values
    for leak in ("crash@example.com", secret, "x-selfie-shots", "x-selfie-lengths", *session_values):
        assert leak not in payload, leak[:12]
    request = captured.events[0]["request"]
    assert set(request) <= {"method", "url", "headers"} and "data" not in request
    assert captured.events[0]["user"] == {"id": str(user.id)}
    assert len(payload) < 60_000  # no image data


def test_retention_checks_in_only_after_a_successful_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import tasks

    pings: list[str] = []
    monkeypatch.setattr(monitoring, "heartbeat", lambda url: pings.append(url) or True)
    monkeypatch.setattr(get_settings(), "retention_heartbeat_url", "http://glitchtip:8000/hb/1")
    tasks.run_retention()  # the task body, as the worker runs it
    assert pings == ["http://glitchtip:8000/hb/1"]

    def broken(db: object) -> None:
        raise RuntimeError("retention failed")

    monkeypatch.setattr("app.services.retention.run_retention", broken)
    with pytest.raises(RuntimeError):
        tasks.run_retention()  # the task body, as the worker runs it
    assert pings == ["http://glitchtip:8000/hb/1"]  # no check-in: GlitchTip alerts


def test_heartbeat_sends_nothing_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    calls: list[tuple[str, dict[str, object]]] = []

    def record(url: str, **kw: object) -> httpx.Response:
        calls.append((url, kw))
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", record)
    assert monitoring.heartbeat("http://glitchtip:8000/hb/1") is True
    assert calls == [("http://glitchtip:8000/hb/1", {"timeout": 5})]  # no body, params or headers
    assert monitoring.heartbeat("") is False

    def down(url: str, **kw: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", down)
    assert monitoring.heartbeat("http://glitchtip:8000/hb/1") is False
