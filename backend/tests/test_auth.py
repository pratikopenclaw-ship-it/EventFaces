from fastapi.testclient import TestClient

from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE
from app.main import app
from tests.conftest import PASSWORD, FakeMailer, new_client

EMAIL = "alice@example.com"


def _signup(client: TestClient, email: str = EMAIL) -> None:
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert r.status_code == 202, r.text


def test_signup_verify_login_me(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert client.get("/api/me").json()["email_verified_at"] is None

    token = mailer.last_link_token(EMAIL)
    r = client.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200
    assert r.json()["email_verified_at"] is not None

    # verification links are single-use
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400

    me = client.get("/api/me").json()
    assert me["email"] == EMAIL and me["role"] == "attendee"


def test_login_sets_httponly_cookies(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    set_cookie = ";".join(r.headers.get_list("set-cookie")).lower()
    assert f"{ACCESS_COOKIE}=" in set_cookie and f"{REFRESH_COOKIE}=" in set_cookie
    assert set_cookie.count("httponly") >= 2
    assert "access_token" not in r.text  # tokens never in the body


def test_duplicate_signup_does_not_reveal_account(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    r = client.post("/api/auth/signup", json={"email": EMAIL, "password": "another-password-1"})
    assert r.status_code == 202
    assert "already have an account" in mailer.outbox[-1].body


def test_wrong_password_and_unknown_user(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    r1 = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-password"})
    r2 = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_me_requires_auth() -> None:
    assert new_client().get("/api/me").status_code == 401


def test_password_reset_flow_revokes_sessions(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    other = new_client()
    assert other.post("/api/auth/forgot-password", json={"email": EMAIL}).status_code == 200
    token = mailer.last_link_token(EMAIL)
    new_pw = "brand-new-password-42"
    assert other.post("/api/auth/reset-password", json={"token": token, "password": new_pw}).status_code == 200
    assert other.post("/api/auth/reset-password", json={"token": token, "password": new_pw}).status_code == 400

    # old refresh token no longer works
    assert client.post("/api/auth/refresh").status_code == 401
    assert other.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    assert other.post("/api/auth/login", json={"email": EMAIL, "password": new_pw}).status_code == 200


def test_forgot_password_unknown_email_is_generic(client: TestClient, mailer: FakeMailer) -> None:
    r = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == 200
    assert mailer.outbox == []


def test_refresh_rotates_and_old_token_is_rejected(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    old_refresh = client.cookies.get(REFRESH_COOKIE)

    assert client.post("/api/auth/refresh").status_code == 200
    assert client.cookies.get(REFRESH_COOKIE) != old_refresh

    replay = new_client()
    replay.cookies.set(REFRESH_COOKIE, old_refresh)
    assert replay.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_refresh(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    refresh = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/api/auth/logout").status_code == 204

    replay = new_client()
    replay.cookies.set(REFRESH_COOKIE, refresh)
    assert replay.post("/api/auth/refresh").status_code == 401


def test_csrf_required_for_mutations(mailer: FakeMailer) -> None:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 403 and "CSRF" in r.text

    c.get("/api/auth/csrf")
    r = c.post(
        "/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"x-csrf-token": "forged"},
    )
    assert r.status_code == 403


def test_login_rate_limited(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    codes = [
        client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-password"}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429
    # even the right password is refused while limited
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 429


def test_login_accepts_any_string_email(client: TestClient, mailer: FakeMailer) -> None:
    # Unknown/odd addresses get the normal 401, not a 422 that differs from a wrong password.
    r = client.post("/api/auth/login", json={"email": "admin@eventfaces.local", "password": "x" * 12})
    assert r.status_code == 401


def test_security_headers_on_api_responses(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cross-origin-resource-policy"] == "same-origin"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "server" not in {k.lower() for k in r.headers} or "uvicorn" not in r.headers.get("server", "")


def test_only_the_csrf_cookie_is_script_readable(client: TestClient, mailer: FakeMailer) -> None:
    _signup(client)
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    cookies = {c.split("=", 1)[0].strip(): c.lower() for c in r.headers.get_list("set-cookie")}
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        assert "httponly" in cookies[name] and "samesite" in cookies[name]
    csrf = client.get("/api/auth/csrf").headers["set-cookie"].lower()
    assert "httponly" not in csrf and "samesite=strict" in csrf  # double-submit token, by design
