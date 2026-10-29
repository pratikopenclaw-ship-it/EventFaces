"""APNs push: payloads carry no personal data, the sender talks APNs correctly, dead
tokens are dropped, and the queued-search / moderation hooks fire."""

import json
import uuid
from collections.abc import Callable, Iterator

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Device, Event, MemberRole, ModerationMode, User
from app.services import push, search_queue
from tests.helpers import selfie_set

KEY = ec.generate_private_key(ec.SECP256R1())
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
TOKEN = "ab" * 32


class FakeAPNs:
    def __init__(self, status: int = 200, reason: str = "") -> None:
        self.status, self.reason = status, reason
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status == 200:
            return httpx.Response(200)
        return httpx.Response(self.status, json={"reason": self.reason})


@pytest.fixture
def apns(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAPNs]:
    s = get_settings()
    for name, value in {"apns_key_p8": PEM, "apns_key_id": "KEY1234567", "apns_team_id": "TEAM123456", "apns_topic": "app.eventfaces.ios", "apns_env": "sandbox"}.items():
        monkeypatch.setattr(s, name, value)
    fake = FakeAPNs()
    push.set_transport(httpx.MockTransport(fake.handler))
    yield fake
    push.set_transport(None)


def _device(db: Session, user: User, token: str | None = TOKEN, env: str = "sandbox", revoked: bool = False) -> Device:
    from app.core.security import utcnow

    d = Device(
        user_id=user.id, session_id=uuid.uuid4(), name="Phone", platform="ios", app_version="1.0.0",
        public_key="B" + "A" * 87, apns_token=token, apns_env=env, revoked_at=utcnow() if revoked else None,
    )
    db.add(d)
    db.commit()
    return d


@pytest.mark.parametrize("kind", ["search_ready", "search_rejected", "moderation_pending", "new_photos"])
def test_payload_has_only_ids_and_localization_keys(kind: push.Kind) -> None:
    event_id = uuid.uuid4()
    body = push.payload(push.Notice(kind, event_id, search_id="s-1"))
    assert set(body) <= push.PAYLOAD_KEYS
    assert body["aps"] == {"alert": {"title-loc-key": f"push.{kind}.title", "loc-key": f"push.{kind}.body"}, "sound": "default"}
    assert body["event_id"] == str(event_id) and body["kind"] == kind
    # Nothing human-readable beyond the keys: no text, names, counts or images.
    assert "body" not in body["aps"]["alert"] and "title" not in body["aps"]["alert"]  # type: ignore[index]


def test_sender_speaks_apns(apns: FakeAPNs, db: Session, make_user: Callable[..., User]) -> None:
    u = make_user("pushme@example.com")
    _device(db, u)
    event_id = uuid.uuid4()
    assert push.notify_users([u.id], push.Notice("search_ready", event_id)) == 1
    (req,) = apns.requests
    assert req.url == f"https://api.sandbox.push.apple.com/3/device/{TOKEN}"
    assert req.headers["apns-topic"] == "app.eventfaces.ios" and req.headers["apns-push-type"] == "alert"
    provider = req.headers["authorization"].split(" ", 1)[1]
    assert jwt.get_unverified_header(provider) == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    assert jwt.decode(provider, KEY.public_key(), algorithms=["ES256"])["iss"] == "TEAM123456"
    sent = json.loads(req.content)
    assert sent == push.payload(push.Notice("search_ready", event_id))
    assert "pushme" not in req.content.decode() and u.email not in req.content.decode()


def test_only_live_devices_in_the_configured_environment(apns: FakeAPNs, db: Session, make_user: Callable[..., User]) -> None:
    u = make_user("envs@example.com")
    _device(db, u, token="cd" * 32, revoked=True)
    _device(db, u, token="ef" * 32, env="production")
    _device(db, u, token=None)
    assert push.notify_users([u.id], push.Notice("search_ready", uuid.uuid4())) == 0
    assert apns.requests == []


@pytest.mark.parametrize(("status", "reason", "dropped"), [(410, "Unregistered", True), (400, "BadDeviceToken", True), (500, "InternalServerError", False), (429, "TooManyRequests", False)])
def test_dead_tokens_are_dropped(status: int, reason: str, dropped: bool, apns: FakeAPNs, db: Session, make_user: Callable[..., User]) -> None:
    apns.status, apns.reason = status, reason
    u = make_user(f"dead-{status}@example.com")
    d = _device(db, u)
    push.notify_users([u.id], push.Notice("search_ready", uuid.uuid4()))
    db.refresh(d)
    assert (d.apns_token is None) is dropped


def test_push_is_off_until_configured(db: Session, make_user: Callable[..., User]) -> None:
    fake = FakeAPNs()
    push.set_transport(httpx.MockTransport(fake.handler))
    try:
        u = make_user("off@example.com")
        _device(db, u)
        assert not push.enabled()
        assert push.notify_users([u.id], push.Notice("search_ready", uuid.uuid4())) == 0
        assert fake.requests == []
    finally:
        push.set_transport(None)


def test_production_refuses_a_malformed_apns_key() -> None:
    base = {k: v for k, v in get_settings().model_dump().items() if k != "environment"}
    with pytest.raises(ValueError, match="APNS_KEY_P8"):
        Settings(**{**base, "environment": "production", "apns_key_p8": "not a key"})


def test_queued_search_notifies_the_searcher(
    apns: FakeAPNs, db: Session, make_event: Callable[..., Event], make_user: Callable[..., User], add_member: Callable[..., object]
) -> None:
    from app.services.search import FACE_CONSENT_VERSION
    from app.core.security import utcnow

    event = make_event("Push Party")
    u = make_user("queued-push@example.com")
    u.face_consent_at, u.face_consent_version = utcnow(), FACE_CONSENT_VERSION
    db.commit()
    add_member(event, u)
    _device(db, u)
    search_queue.process(search_queue.Job(u.id, event.id, selfie_set(0)))
    assert len(apns.requests) == 1
    sent = json.loads(apns.requests[0].content)
    assert sent["kind"] == "search_ready" and sent["event_id"] == str(event.id)
    assert "Push Party" not in apns.requests[0].content.decode()


def test_guest_upload_awaiting_review_notifies_organizers_only(
    apns: FakeAPNs, db: Session, make_event: Callable[..., Event], make_user: Callable[..., User], add_member: Callable[..., object], login_as: Callable[..., object]
) -> None:
    from tests.helpers import group_photo_bytes
    from tests.test_guest_uploads import upload  # the real presigned-PUT flow

    event = make_event("Review Party", guest_upload_enabled=True, moderation_mode=ModerationMode.manual)
    org, guest, other = make_user("org-push@example.com"), make_user("guest-push@example.com"), make_user("other-push@example.com")
    add_member(event, org, role=MemberRole.organizer)
    add_member(event, guest)
    add_member(event, other)
    for u, tok in ((org, "01" * 32), (guest, "02" * 32), (other, "03" * 32)):
        _device(db, u, token=tok)
    _, _, complete = upload(login_as(guest), event, group_photo_bytes())
    assert complete.status_code == 200, complete.text
    assert [r.url.path for r in apns.requests] == [f"/3/device/{'01' * 32}"]
    assert json.loads(apns.requests[0].content)["kind"] == "moderation_pending"


def test_network_errors_keep_the_token_and_never_raise(apns: FakeAPNs, db: Session, make_user: Callable[..., User]) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    push.set_transport(httpx.MockTransport(boom))
    u = make_user("offline@example.com")
    d = _device(db, u)
    assert push.notify_users([u.id], push.Notice("search_ready", uuid.uuid4())) == 1
    db.refresh(d)
    assert d.apns_token == TOKEN


def test_notify_safely_swallows_every_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object) -> int:
        raise RuntimeError("APNs down")

    monkeypatch.setattr(push, "notify_users", explode)
    push.notify_safely([uuid.uuid4()], push.Notice("search_ready", uuid.uuid4()))  # no exception


def test_real_client_uses_http2_against_the_configured_host(apns: FakeAPNs, monkeypatch: pytest.MonkeyPatch) -> None:
    push.set_transport(None)
    monkeypatch.setattr(get_settings(), "apns_env", "production")
    with push._client() as c:
        assert str(c.base_url) == "https://api.push.apple.com"
        assert c._transport._pool._http2 is True  # type: ignore[attr-defined]


def test_provider_token_is_reused(apns: FakeAPNs) -> None:
    assert push._provider_token() == push._provider_token()
