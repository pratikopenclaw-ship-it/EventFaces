"""UX-003: a new attendee who arrives via a QR/join link and signs up must end up back at
that event after verifying their email. The destination travels in the verification link,
so the server accepts only a strict /join/<slug>[?code=…] shape (never an open redirect)."""

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from tests.conftest import PASSWORD, FakeMailer, new_client


def _verify_link(mailer: FakeMailer, email: str) -> str:
    mail = next(m for m in reversed(mailer.outbox) if m.to == email)
    return mail.body.split("\n\n")[1].strip().split()[0]


@pytest.mark.parametrize("dest", ["/join/demo-party-2u6m7p", "/join/demo-party-2u6m7p?code=URPHP25E"])
def test_join_destination_survives_signup(dest: str, mailer: FakeMailer) -> None:
    r = new_client().post("/api/auth/signup", json={"accept_terms": True, "email": "qr-guest@example.com", "password": PASSWORD, "next": dest})
    assert r.status_code == 202, r.text
    link = urlsplit(_verify_link(mailer, "qr-guest@example.com"))
    assert link.path == "/verify-email"
    assert unquote(parse_qs(link.query)["next"][0]) == dest


def test_signup_without_destination_has_plain_link(mailer: FakeMailer) -> None:
    new_client().post("/api/auth/signup", json={"accept_terms": True, "email": "plain@example.com", "password": PASSWORD})
    assert "next=" not in _verify_link(mailer, "plain@example.com")


@pytest.mark.parametrize(
    "dest",
    [
        "https://evil.example/join/x",
        "//evil.example/join/x",
        "/join/../admin/events",
        "/join/x/../../admin",
        "/events",
        "/join/",
        "/join/UPPER",
        "/join/x?code=ABC&next=https://evil.example",
        "/join/x?code=<script>",
        "/join/x\r\nSet-Cookie: a=b",
        "javascript:alert(1)",
        "/join/" + "a" * 90,
    ],
)
def test_other_destinations_are_rejected(dest: str) -> None:
    r = new_client().post("/api/auth/signup", json={"accept_terms": True, "email": "attacker@example.com", "password": PASSWORD, "next": dest})
    assert r.status_code == 422, (dest, r.status_code)
