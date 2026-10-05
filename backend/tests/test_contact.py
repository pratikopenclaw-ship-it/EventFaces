"""The contact form: emailed to the operator with Reply-To set to the sender, never stored,
rate limited per IP and per sender, header-injection safe, and bots fed a fake success."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import Mail, build_message
from tests.conftest import FakeMailer

GOOD = {"name": "Dana Organizer", "email": "dana@example.com", "topic": "organizer", "message": "We run 10 weddings a year. Can we talk?"}


def row_counts(db: Session) -> dict[str, int]:
    tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")).scalars()
    return {t: db.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0 for t in tables}  # noqa: S608 - names from pg_tables


def test_a_message_is_emailed_to_the_operator_and_not_stored(client: TestClient, mailer: FakeMailer, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "contact_email", "hello@operator.example.org")
    before = row_counts(db)
    r = client.post("/api/contact", json=GOOD)
    assert r.status_code == 202 and r.json() == {"status": "sent"}
    mail = mailer.outbox[-1]
    assert mail.to == "hello@operator.example.org" and mail.reply_to == "dana@example.com"
    assert "Organizing an event" in mail.subject and "Dana Organizer" in mail.subject
    assert GOOD["message"] in mail.body
    assert row_counts(db) == before  # nothing persisted


def test_the_recipient_falls_back_to_the_legal_email(client: TestClient, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "contact_email", "")
    monkeypatch.setattr(get_settings(), "legal_email", "legal@operator.example.org")
    assert client.post("/api/contact", json=GOOD).status_code == 202
    assert mailer.outbox[-1].to == "legal@operator.example.org"


def test_header_injection_is_flattened() -> None:
    msg = build_message(Mail(to="ops@example.org", subject="Hi\r\nBcc: victim@example.org", body="x", reply_to="a@example.com\r\nBcc: v@example.org"))
    assert "Bcc" not in msg
    assert "\n" not in msg["Subject"] and "\n" not in msg["Reply-To"]


def test_header_injection_through_the_form_is_refused_or_flattened(client: TestClient, mailer: FakeMailer) -> None:
    r = client.post("/api/contact", json=GOOD | {"email": "dana@example.com\r\nBcc: victim@example.org"})
    assert r.status_code == 422  # not an email address
    r = client.post("/api/contact", json=GOOD | {"name": "Dana\r\nBcc: victim@example.org"})
    assert r.status_code == 202
    assert "Bcc" not in build_message(mailer.outbox[-1])


def test_the_honeypot_looks_successful_but_sends_nothing(client: TestClient, mailer: FakeMailer) -> None:
    r = client.post("/api/contact", json=GOOD | {"website": "http://spam.example"})
    assert r.status_code == 202 and r.json() == {"status": "sent"}
    assert mailer.outbox == []


@pytest.mark.parametrize("bad", [{"message": "short"}, {"topic": "sales"}, {"email": "not-an-email"}, {"name": ""}, {"message": "x" * 5001}])
def test_invalid_messages_are_refused(client: TestClient, mailer: FakeMailer, bad: dict[str, str]) -> None:
    assert client.post("/api/contact", json=GOOD | bad).status_code == 422
    assert mailer.outbox == []


def test_rate_limited_per_sender_even_across_ips(client: TestClient, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "contact_rate_limit", "100/3600")
    codes = [client.post("/api/contact", json=GOOD).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]
    assert client.post("/api/contact", json=GOOD | {"email": "someone-else@example.com"}).status_code == 202


def test_a_mail_outage_is_reported_without_details(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    class Down:
        def send(self, mail: Mail) -> None:
            raise ConnectionRefusedError(f"cannot deliver to {mail.reply_to}")

    monkeypatch.setattr("app.api.routes.contact.get_mailer", lambda: Down())
    r = client.post("/api/contact", json=GOOD)
    assert r.status_code == 503 and r.headers["retry-after"] == "60"
    assert "ConnectionRefusedError" in caplog.text  # the failure is logged...
    assert "dana@example.com" not in caplog.text and GOOD["message"] not in caplog.text  # ...without details
