"""Mobile app authentication: passwordless codes, magic links, device-bound sessions.

The app must never be a weaker path than the web app: codes are rate-limited, locked out
and single-use; sessions end on logout, password reset and account deletion exactly like
web sessions; a refresh token only works with a signature from the device's key; tokens
can't cross between the cookie and bearer transports.
"""

import base64
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE, create_access_token
from app.main import app
from app.models import Device, User
from app.services import mobile_auth
from tests.conftest import PASSWORD, FakeMailer, new_client


class DeviceKey:
    """Stands in for the Secure Enclave key."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public_b64 = base64.b64encode(self.key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)).decode()

    def sign(self, refresh_token: str, device_id: str, ts: int) -> str:
        msg = mobile_auth.refresh_message(refresh_token, uuid.UUID(device_id), ts)
        return base64.b64encode(self.key.sign(msg, ec.ECDSA(hashes.SHA256()))).decode()


@dataclass
class AppSession:
    client: TestClient
    key: DeviceKey
    access: str
    refresh: str
    device_id: str

    def refresh_request(self, *, token: str | None = None, ts: int | None = None, key: DeviceKey | None = None, device_id: str | None = None):  # type: ignore[no-untyped-def]
        token = token or self.refresh
        ts = int(time.time()) if ts is None else ts
        device_id = device_id or self.device_id
        sig = (key or self.key).sign(token, device_id, ts)
        return app_client().post("/api/mobile/auth/refresh", json={"refresh_token": token, "device_id": device_id, "ts": ts, "signature": sig})


def app_client(access: str | None = None) -> TestClient:
    c = TestClient(app)
    c.headers["X-App-Version"] = "1.0.0"
    if access:
        c.headers["Authorization"] = f"Bearer {access}"
    return c


def last_code(mailer: FakeMailer, to: str) -> str:
    mail = next(m for m in reversed(mailer.outbox) if m.to == to)
    return mail.subject.split()[0]


def last_magic(mailer: FakeMailer, to: str) -> str:
    mail = next(m for m in reversed(mailer.outbox) if m.to == to)
    return mail.body.split("/m/signin?t=")[1].split()[0]


def request_code(email: str):  # type: ignore[no-untyped-def]
    return app_client().post("/api/mobile/auth/code/request", json={"email": email})


def verify(email: str, code: str, key: DeviceKey | None = None):  # type: ignore[no-untyped-def]
    key = key or DeviceKey()
    return app_client().post(
        "/api/mobile/auth/code/verify", json={"accept_terms": True, "email": email, "code": code, "device": {"name": "Test iPhone", "public_key": key.public_b64}}
    )


def sign_in(mailer: FakeMailer, email: str) -> AppSession:
    key = DeviceKey()
    assert request_code(email).status_code == 202
    r = verify(email, last_code(mailer, email), key)
    assert r.status_code == 200, r.text
    body = r.json()
    return AppSession(app_client(body["access_token"]), key, body["access_token"], body["refresh_token"], body["device_id"])


# --- codes ----------------------------------------------------------------------------------


def test_code_sign_in_creates_a_verified_passwordless_account(mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "new-phone@example.com")
    me = s.client.get("/api/me")
    assert me.status_code == 200 and me.json()["email"] == "new-phone@example.com"
    user = db.scalar(select(User).where(User.email == "new-phone@example.com"))
    assert user is not None and user.password_hash is None and user.email_verified_at is not None
    device = db.scalar(select(Device).where(Device.user_id == user.id))
    assert device is not None and device.public_key == s.key.public_b64 and device.app_version == "1.0.0"


def test_requesting_a_code_creates_nothing_and_answers_the_same_for_any_address(
    mailer: FakeMailer, make_user: Callable[..., User], db: Session
) -> None:
    make_user("exists@example.com")
    a, b = request_code("exists@example.com"), request_code("nobody-yet@example.com")
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (202, a.json())
    assert db.scalar(select(User).where(User.email == "nobody-yet@example.com")) is None
    assert {m.to for m in mailer.outbox} >= {"exists@example.com", "nobody-yet@example.com"}


def test_mobile_auth_endpoints_never_set_cookies(mailer: FakeMailer) -> None:
    r = request_code("cookies@example.com")
    assert "set-cookie" not in r.headers
    r = verify("cookies@example.com", last_code(mailer, "cookies@example.com"))
    assert r.status_code == 200 and "set-cookie" not in r.headers


def test_code_is_single_use(mailer: FakeMailer) -> None:
    request_code("once@example.com")
    code = last_code(mailer, "once@example.com")
    assert verify("once@example.com", code).status_code == 200
    assert verify("once@example.com", code).status_code == 400


def test_a_new_code_replaces_the_old_code_and_link(mailer: FakeMailer) -> None:
    request_code("again@example.com")
    old_code, old_magic = last_code(mailer, "again@example.com"), last_magic(mailer, "again@example.com")
    request_code("again@example.com")
    new_code = last_code(mailer, "again@example.com")
    if new_code != old_code:  # 1-in-a-million collision would make the first check meaningless
        assert verify("again@example.com", old_code).status_code == 400
    r = app_client().post("/api/mobile/auth/magic", json={"accept_terms": True, "token": old_magic, "device": {"name": "x", "public_key": DeviceKey().public_b64}})
    assert r.status_code == 400
    assert verify("again@example.com", new_code).status_code == 200


def test_code_dies_after_too_many_wrong_guesses(mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "join_lockout_attempts", 100)  # isolate the per-code limit
    request_code("guess@example.com")
    code = last_code(mailer, "guess@example.com")
    wrong = "111111" if code != "111111" else "222222"
    for _ in range(get_settings().mobile_code_max_attempts):
        assert verify("guess@example.com", wrong).status_code == 400
    assert verify("guess@example.com", code).status_code == 400  # even the right one now


def test_wrong_codes_lock_out_the_address_like_web_join(mailer: FakeMailer) -> None:
    request_code("lock@example.com")
    for _ in range(get_settings().join_lockout_attempts):
        assert verify("lock@example.com", "000001").status_code == 400
    r = verify("lock@example.com", "000002")
    assert r.status_code == 429
    # A fresh code doesn't lift the lockout.
    get_redis().delete("rl:mcode-req:lock@example.com")
    request_code("lock@example.com")
    assert verify("lock@example.com", last_code(mailer, "lock@example.com")).status_code == 429


def test_code_requests_are_rate_limited_per_address(mailer: FakeMailer) -> None:
    limit = int(get_settings().mobile_code_request_rate_limit.split("/")[0])
    codes = [request_code("spam@example.com").status_code for _ in range(limit + 1)]
    assert codes[:limit] == [202] * limit and codes[-1] == 429


def test_expired_code_is_rejected(mailer: FakeMailer) -> None:
    request_code("late@example.com")
    code = last_code(mailer, "late@example.com")
    r = get_redis()
    for key in r.scan_iter("mcode:signin:*"):
        r.delete(key)  # what the TTL does
    assert verify("late@example.com", code).status_code == 400


def test_concurrent_first_sign_ins_create_one_account(mailer: FakeMailer, db: Session) -> None:
    # Two codes can't be live at once, so race the account creation itself.
    with ThreadPoolExecutor(4) as pool:
        users = list(pool.map(lambda _: _create("race@example.com"), range(4)))
    assert len({u for u in users}) == 1
    assert db.scalar(select(User.id).where(User.email == "race@example.com")) == users[0]


def _create(email: str) -> uuid.UUID:
    from app.core.db import SessionLocal

    with SessionLocal() as s:
        user = mobile_auth.find_or_create_user(s, email)
        s.commit()
        return user.id


# --- magic links ------------------------------------------------------------------------------


def test_magic_link_signs_in_once_and_kills_the_code(mailer: FakeMailer) -> None:
    request_code("magic@example.com")
    token, code = last_magic(mailer, "magic@example.com"), last_code(mailer, "magic@example.com")
    body = {"token": token, "accept_terms": True, "device": {"name": "x", "public_key": DeviceKey().public_b64}}
    r = app_client().post("/api/mobile/auth/magic", json=body)
    assert r.status_code == 200
    assert app_client(r.json()["access_token"]).get("/api/me").json()["email"] == "magic@example.com"
    assert app_client().post("/api/mobile/auth/magic", json=body).status_code == 400
    assert verify("magic@example.com", code).status_code == 400


def test_bad_device_keys_are_refused(mailer: FakeMailer) -> None:
    request_code("badkey@example.com")
    code = last_code(mailer, "badkey@example.com")
    not_on_curve = base64.b64encode(b"\x04" + b"\x01" * 64).decode()
    r = app_client().post("/api/mobile/auth/code/verify", json={"accept_terms": True, "email": "badkey@example.com", "code": code, "device": {"name": "x", "public_key": not_on_curve}})
    assert r.status_code == 422


# --- existing accounts ------------------------------------------------------------------------


def test_existing_password_account_can_use_codes_and_keeps_its_password(
    mailer: FakeMailer, make_user: Callable[..., User]
) -> None:
    u = make_user("both@example.com")
    s = sign_in(mailer, "both@example.com")
    assert s.client.get("/api/me").json()["id"] == str(u.id)
    assert new_client().post("/api/auth/login", json={"email": "both@example.com", "password": PASSWORD}).status_code == 200


def test_passwordless_accounts_cannot_log_in_with_a_password(mailer: FakeMailer) -> None:
    sign_in(mailer, "nopass@example.com")
    for pw in ["", "anything-at-all", "!"]:
        r = new_client().post("/api/auth/login", json={"email": "nopass@example.com", "password": pw})
        assert r.status_code in (401, 422)


# --- device-bound refresh ---------------------------------------------------------------------


def test_signed_refresh_rotates_tokens(mailer: FakeMailer) -> None:
    s = sign_in(mailer, "rotate@example.com")
    r = s.refresh_request()
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != s.refresh and new["device_id"] == s.device_id
    assert app_client(new["access_token"]).get("/api/me").status_code == 200


@pytest.mark.parametrize("tamper", ["other_key", "stale", "future", "other_device", "garbage_sig"])
def test_refresh_needs_this_devices_fresh_signature(tamper: str, mailer: FakeMailer) -> None:
    s = sign_in(mailer, f"tamper-{tamper}@example.com")
    skew = get_settings().mobile_signature_skew_seconds
    if tamper == "other_key":
        r = s.refresh_request(key=DeviceKey())
    elif tamper == "stale":
        r = s.refresh_request(ts=int(time.time()) - skew - 5)
    elif tamper == "future":
        r = s.refresh_request(ts=int(time.time()) + skew + 5)
    elif tamper == "other_device":
        r = s.refresh_request(device_id=str(uuid.uuid4()))
    else:
        r = app_client().post("/api/mobile/auth/refresh", json={"refresh_token": s.refresh, "device_id": s.device_id, "ts": int(time.time()), "signature": "AAAAAAAAAAAA"})
    assert r.status_code == 401
    assert s.refresh_request().status_code == 200  # the real device still can


def test_a_captured_refresh_request_cannot_be_replayed(mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> None:
    # No reuse grace: without the signature cache, the replay would reach reuse detection
    # and an attacker holding a captured request could sign the real user out.
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    s = sign_in(mailer, "replay@example.com")
    ts = int(time.time())
    body = {"refresh_token": s.refresh, "device_id": s.device_id, "ts": ts, "signature": s.key.sign(s.refresh, s.device_id, ts)}
    first = app_client().post("/api/mobile/auth/refresh", json=body)
    assert first.status_code == 200
    assert app_client().post("/api/mobile/auth/refresh", json=body).status_code == 401
    # The replay was stopped by the signature cache, before reuse detection: the
    # legitimate device keeps its session.
    assert app_client(first.json()["access_token"]).get("/api/me").status_code == 200


def test_reusing_a_rotated_refresh_token_revokes_the_session(mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)
    s = sign_in(mailer, "stolen@example.com")
    new = s.refresh_request().json()
    time.sleep(1.1)  # a fresh ts gives a fresh signature
    assert s.refresh_request().status_code == 401  # the old token again: theft
    assert app_client(new["access_token"]).get("/api/me").status_code == 401  # whole session ended


def test_refresh_token_only_works_for_its_own_device(mailer: FakeMailer) -> None:
    a, b = sign_in(mailer, "dev-a@example.com"), sign_in(mailer, "dev-b@example.com")
    # B's device, B's signature, but A's refresh token.
    r = app_client().post(
        "/api/mobile/auth/refresh",
        json={"refresh_token": a.refresh, "device_id": b.device_id, "ts": int(time.time()), "signature": b.key.sign(a.refresh, b.device_id, int(time.time()))},
    )
    assert r.status_code == 401
    assert a.refresh_request().status_code == 200


def test_app_refresh_token_is_refused_by_the_web_refresh_endpoint(mailer: FakeMailer) -> None:
    s = sign_in(mailer, "web-refresh@example.com")
    c = new_client()
    c.cookies.set(REFRESH_COOKIE, s.refresh)
    assert c.post("/api/auth/refresh").status_code == 401
    assert s.refresh_request().status_code == 200  # not rotated away by the attempt


def test_web_refresh_token_is_refused_by_the_app_refresh_endpoint(make_user: Callable[..., User], login_as: Callable[..., TestClient], mailer: FakeMailer) -> None:
    web = login_as(make_user("web-only@example.com"))
    web_refresh = web.cookies.get(REFRESH_COOKIE)
    app_s = sign_in(mailer, "web-only@example.com")
    r = app_s.refresh_request(token=web_refresh)
    assert r.status_code == 401
    assert web.post("/api/auth/refresh").status_code == 200


# --- transport separation ---------------------------------------------------------------------


def test_tokens_cannot_cross_transports(mailer: FakeMailer, make_user: Callable[..., User], login_as: Callable[..., TestClient]) -> None:
    s = sign_in(mailer, "cross@example.com")
    cookie_with_app_token = new_client()
    cookie_with_app_token.cookies.set(ACCESS_COOKIE, s.access)
    assert cookie_with_app_token.get("/api/me").status_code == 401
    web = login_as(make_user("cross-web@example.com"))
    assert app_client(web.cookies.get(ACCESS_COOKIE)).get("/api/me").status_code == 401
    # Hand-made tokens: right signature, wrong audience.
    u_id = uuid.UUID(s.client.get("/api/me").json()["id"])
    assert app_client(create_access_token(u_id, "attendee", uuid.uuid4(), audience="web")).get("/api/me").status_code == 401


def test_bearer_requests_ignore_cookies(mailer: FakeMailer, make_user: Callable[..., User], login_as: Callable[..., TestClient]) -> None:
    web = login_as(make_user("cookie-user@example.com"))
    # A broken bearer header next to a valid session cookie: judged on the header alone.
    web.headers["Authorization"] = "Bearer not-a-token"
    web.headers["X-App-Version"] = "1.0.0"
    assert web.get("/api/me").status_code == 401


@pytest.mark.parametrize("header", ["Bearer ", "Bearer", "Basic dXNlcjpwYXNz", "Token abc"])
def test_malformed_authorization_never_authenticates_or_skips_csrf(header: str, make_user: Callable[..., User], login_as: Callable[..., TestClient]) -> None:
    c = app_client()
    c.headers["Authorization"] = header
    assert c.post("/api/join", json={"slug": "x", "code": "y"}).status_code == 401
    assert c.get("/api/me").status_code == 401
    # With a session cookie, an Authorization header doesn't switch CSRF off.
    web = login_as(make_user(f"csrf-{abs(hash(header))}@example.com"))
    del web.headers["X-CSRF-Token"]
    web.headers["Authorization"] = header
    web.headers["X-App-Version"] = "1.0.0"
    assert web.patch("/api/me/preferences", json={"theme": "dark"}).status_code == 403


# --- logout, devices, revocation parity --------------------------------------------------------


def test_logout_ends_the_session_now(mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "bye@example.com")
    s.client.put("/api/me/devices/current/push", json={"token": "ab" * 32, "env": "sandbox"})
    assert s.client.post("/api/mobile/auth/logout").status_code == 204
    assert s.client.get("/api/me").status_code == 401
    assert s.refresh_request().status_code == 401
    device = db.get(Device, uuid.UUID(s.device_id))
    db.refresh(device)
    assert device.revoked_at is not None and device.apns_token is None


def test_device_list_and_remote_revoke(mailer: FakeMailer) -> None:
    phone, tablet = sign_in(mailer, "two@example.com"), sign_in(mailer, "two@example.com")
    devices = phone.client.get("/api/me/devices").json()
    assert {d["id"] for d in devices} == {phone.device_id, tablet.device_id}
    assert [d["current"] for d in devices if d["id"] == phone.device_id] == [True]
    assert phone.client.delete(f"/api/me/devices/{tablet.device_id}").status_code == 204
    assert tablet.client.get("/api/me").status_code == 401
    assert tablet.refresh_request().status_code == 401
    assert [d["id"] for d in phone.client.get("/api/me/devices").json()] == [phone.device_id]


def test_cannot_revoke_someone_elses_device(mailer: FakeMailer) -> None:
    a, b = sign_in(mailer, "idor-a@example.com"), sign_in(mailer, "idor-b@example.com")
    assert b.client.delete(f"/api/me/devices/{a.device_id}").status_code == 404
    assert a.client.get("/api/me").status_code == 200
    assert a.device_id not in {d["id"] for d in b.client.get("/api/me/devices").json()}


def test_password_reset_signs_out_every_device(mailer: FakeMailer, make_user: Callable[..., User]) -> None:
    make_user("reset-app@example.com")
    s = sign_in(mailer, "reset-app@example.com")
    c = new_client()
    c.post("/api/auth/forgot-password", json={"email": "reset-app@example.com"})
    token = mailer.last_link_token("reset-app@example.com")
    assert c.post("/api/auth/reset-password", json={"token": token, "password": "new-password-123"}).status_code == 200
    assert s.client.get("/api/me").status_code == 401
    assert s.refresh_request().status_code == 401


def test_web_logout_leaves_app_sessions_alone(mailer: FakeMailer, make_user: Callable[..., User], login_as: Callable[..., TestClient]) -> None:
    web = login_as(make_user("mixed@example.com"))
    s = sign_in(mailer, "mixed@example.com")
    web.post("/api/auth/logout")
    assert s.client.get("/api/me").status_code == 200


def test_passwordless_account_deletion_needs_an_emailed_code(mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "delete-app@example.com")
    assert s.client.request("DELETE", "/api/me", json={"password": "guess"}).status_code == 403
    assert s.client.request("DELETE", "/api/me", json={}).status_code == 403
    assert s.client.post("/api/me/reauth-code").status_code == 202
    code = mailer.outbox[-1].body.split(": ")[1].split()[0]
    wrong = "123456" if code != "123456" else "654321"
    assert s.client.request("DELETE", "/api/me", json={"code": wrong}).status_code == 403
    r = s.client.request("DELETE", "/api/me", json={"code": code})
    assert r.status_code == 200
    assert db.scalar(select(User).where(User.email == "delete-app@example.com")) is None
    assert db.scalar(select(Device).where(Device.id == uuid.UUID(s.device_id))) is None
    assert s.refresh_request().status_code == 401


def test_sign_in_codes_cannot_be_used_to_delete_an_account(mailer: FakeMailer) -> None:
    s = sign_in(mailer, "purpose@example.com")
    request_code("purpose@example.com")  # a sign-in code, not a deletion code
    assert s.client.request("DELETE", "/api/me", json={"code": last_code(mailer, "purpose@example.com")}).status_code == 403


# --- push registration ------------------------------------------------------------------------


def test_push_registration_is_app_only_and_moves_with_the_install(mailer: FakeMailer, make_user: Callable[..., User], login_as: Callable[..., TestClient], db: Session) -> None:
    web = login_as(make_user("web-push@example.com"))
    assert web.put("/api/me/devices/current/push", json={"token": "ab" * 32, "env": "sandbox"}).status_code == 400
    a = sign_in(mailer, "push-a@example.com")
    assert a.client.put("/api/me/devices/current/push", json={"token": "AB" * 32, "env": "sandbox"}).status_code == 204
    # Someone else signs in on the same phone: the token now belongs to their device only.
    b = sign_in(mailer, "push-b@example.com")
    assert b.client.put("/api/me/devices/current/push", json={"token": "ab" * 32, "env": "sandbox"}).status_code == 204
    tokens = dict(db.execute(select(Device.id, Device.apns_token)).all())
    assert tokens[uuid.UUID(a.device_id)] is None and tokens[uuid.UUID(b.device_id)] == "ab" * 32


@pytest.mark.parametrize("token", ["zz" * 32, "ab" * 10, "ab" * 120, "../../etc"])
def test_push_token_format_is_checked(token: str, mailer: FakeMailer) -> None:
    s = sign_in(mailer, f"pushfmt-{uuid.uuid4().hex[:8]}@example.com")
    assert s.client.put("/api/me/devices/current/push", json={"token": token, "env": "sandbox"}).status_code == 422


# --- edge cases ---------------------------------------------------------------------------------


def test_code_sign_in_verifies_an_unverified_account(mailer: FakeMailer, make_user: Callable[..., User], db: Session) -> None:
    u = make_user("unverified-app@example.com", verified=False)
    sign_in(mailer, "unverified-app@example.com")
    db.refresh(u)
    assert u.email_verified_at is not None  # the code proved the inbox


def test_soft_deleted_accounts_cannot_be_signed_into(mailer: FakeMailer, make_user: Callable[..., User], db: Session) -> None:
    from app.core.security import utcnow

    u = make_user("gone@example.com")
    u.deleted_at = utcnow()
    db.commit()
    request_code("gone@example.com")
    assert verify("gone@example.com", last_code(mailer, "gone@example.com")).status_code == 400


def test_push_can_be_switched_off_from_the_device(mailer: FakeMailer, db: Session) -> None:
    s = sign_in(mailer, "push-off@example.com")
    s.client.put("/api/me/devices/current/push", json={"token": "ab" * 32, "env": "sandbox"})
    assert s.client.delete("/api/me/devices/current/push").status_code == 204
    device = db.get(Device, uuid.UUID(s.device_id))
    db.refresh(device)
    assert device.apns_token is None and device.revoked_at is None


def test_app_config_only_knows_ios() -> None:
    assert app_client().get("/api/app/config?platform=android").status_code == 422
