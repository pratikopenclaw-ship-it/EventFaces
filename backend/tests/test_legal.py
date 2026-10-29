"""Legal documents and provable acceptance.

- Texts are versioned: changing an accepted document without bumping its version fails
  (pinned hashes), so nobody is held to words they never saw.
- Every account creation path requires accepting the Terms of Use (and the 16+ statement)
  and records it with version, time, language and channel.
- Users without the current Terms can't use events; organizers without the current
  Organizer Terms (with the data processing agreement) can't manage them. The account,
  its deletion, consent withdrawal, devices and sign-out always stay available.
- The privacy notice lists every cookie the web app sets.
"""

import inspect
import re
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.models import Event, LegalAcceptance, User, UserRole
from app.services import legal
from tests.conftest import PASSWORD, FakeMailer, new_client
from tests.test_mobile_auth import DeviceKey, app_client, last_code, request_code

# Version -> hash of every locale's text. A text change needs a new version (and a new pin).
PINNED = {
    "terms": ("2026-10-03", "0d8148d2e2265c09fd03beaf0443051a0a7b9087f27385b1170b0cea2b78874c"),
    "organizer-terms": ("2026-10-03", "09965e389231e0af2898dc208bb644ba6efe1ece3ecd445cffb70d94f6381ec5"),
    "privacy": ("2026-10-29", "17f8149cafad816d6c952439159562151bd5b2463a357793d925e3b31406e570"),
    "imprint": ("2026-10-03", "b7a0e8615a4924d4040cfacbd25dbe4a0b9f39a11b5e2fe4435cf9739f24b070"),
}


@pytest.mark.parametrize("document", legal.DOCUMENTS)
def test_text_changes_need_a_new_version(document: legal.Document) -> None:
    version, digest = PINNED[document]
    assert legal.VERSIONS[document] == version, "bump the pin together with the version"
    assert legal.fingerprint(document) == digest, f"{document} text changed: bump legal.VERSIONS[{document!r}] and re-pin"


@pytest.mark.parametrize("document", legal.DOCUMENTS)
def test_both_languages_have_the_same_structure(document: legal.Document) -> None:
    de, en = (legal.render(document, loc) for loc in ("de", "en"))
    assert len(de.sections) == len(en.sections)
    assert [len(s.paragraphs) for s in de.sections] == [len(s.paragraphs) for s in en.sections]


def test_every_cookie_the_api_sets_is_in_the_privacy_notice() -> None:
    names = {v for k, v in vars(security).items() if k.endswith("_COOKIE") and isinstance(v, str)}
    assert names == set(legal.DOCUMENTED_COOKIES)
    for locale in legal.LOCALES:
        cookies = next(s for s in legal.render("privacy", locale).sections if "Cookie" in s.heading)
        text = " ".join(cookies.paragraphs)
        for name in names:
            assert f"{name} –" in text, f"{name} missing from the {locale} cookie section"
    # Lifetimes follow the configuration, not hard-coded numbers.
    en = " ".join(next(s for s in legal.render("privacy", "en").sections if "Cookie" in s.heading).paragraphs)
    assert f"{get_settings().access_token_minutes} minutes" in en
    assert f"{get_settings().refresh_token_days} days" in en


def test_cookies_set_in_code_are_the_documented_ones() -> None:
    from app.api import cookies

    used = set(re.findall(r"set_cookie\(\s*(\w+_COOKIE)", inspect.getsource(cookies)))
    assert {getattr(security, n) for n in used} <= set(legal.DOCUMENTED_COOKIES)


def test_unset_identity_shows_placeholders_and_optional_parts_disappear() -> None:
    imprint = legal.render("imprint", "de")
    text = " ".join(p for s in imprint.sections for p in s.paragraphs)
    assert "[operator name]" in text and "[phone]" in text
    assert "Registereintrag" not in [s.heading for s in imprint.sections]  # optional, empty
    assert "{" not in text and "}" not in text


def test_identity_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    for field, value in {
        "legal_operator_name": "Example Photos GmbH",
        "legal_operator_address": "Musterstraße 1\\n10115 Berlin",
        "legal_register": "Amtsgericht Charlottenburg, HRB 1",
        "legal_phone": "+49 30 1",
    }.items():
        monkeypatch.setattr(s, field, value)
    imprint = legal.render("imprint", "de")
    text = " ".join(p for sec in imprint.sections for p in sec.paragraphs)
    assert "Example Photos GmbH" in text and "Musterstraße 1, 10115 Berlin" in text
    assert "Amtsgericht Charlottenburg, HRB 1" in text  # optional part appears once set
    assert "+49 30 1" in text


@pytest.mark.parametrize("document", legal.DOCUMENTS)
def test_documents_are_public_and_versioned(document: str) -> None:
    r = new_client().get(f"/api/legal/{document}", headers={"Accept-Language": "de-DE,de;q=0.9"})
    assert r.status_code == 200
    body = r.json()
    assert (body["document"], body["version"], body["locale"], body["binding_locale"]) == (document, legal.VERSIONS[document], "de", "de")  # type: ignore[index]
    assert body["sections"] and all(s["paragraphs"] for s in body["sections"])
    assert new_client().get(f"/api/legal/{document}?lang=en").json()["locale"] == "en"


def test_unknown_documents_are_refused() -> None:
    assert new_client().get("/api/legal/secret").status_code == 422


# --- acceptance at account creation ------------------------------------------------------------


def _acceptances(db: Session, email: str) -> list[LegalAcceptance]:
    db.expire_all()
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    return list(db.scalars(select(LegalAcceptance).where(LegalAcceptance.user_id == user.id)))


@pytest.mark.parametrize("accept", [None, False, "yes", 1])
def test_signup_requires_accepting_the_terms(accept: object, db: Session) -> None:
    body = {"email": "noterms@example.com", "password": PASSWORD} | ({} if accept is None else {"accept_terms": accept})
    r = new_client().post("/api/auth/signup", json=body)
    assert r.status_code == 422
    assert db.scalar(select(User).where(User.email == "noterms@example.com")) is None


def test_signup_records_the_acceptance(db: Session, mailer: FakeMailer) -> None:
    r = new_client().post("/api/auth/signup", json={"email": "fresh@example.com", "password": PASSWORD, "accept_terms": True}, headers={"Accept-Language": "de"})
    assert r.status_code == 202
    [row] = _acceptances(db, "fresh@example.com")
    assert (row.document, row.version, row.locale, row.channel) == ("terms", legal.VERSIONS["terms"], "de", "web")
    assert row.accepted_at is not None


def test_signup_for_an_existing_address_records_nothing(db: Session, make_user: Callable[..., User], mailer: FakeMailer) -> None:
    make_user("taken@example.com")
    assert new_client().post("/api/auth/signup", json={"email": "taken@example.com", "password": PASSWORD, "accept_terms": True}).status_code == 202
    assert _acceptances(db, "taken@example.com") == []


def test_app_sign_in_requires_and_records_acceptance(db: Session, mailer: FakeMailer) -> None:
    request_code("phone-terms@example.com")
    code = last_code(mailer, "phone-terms@example.com")
    device = {"name": "iPhone", "public_key": DeviceKey().public_b64}
    refused = app_client().post("/api/mobile/auth/code/verify", json={"email": "phone-terms@example.com", "code": code, "device": device})
    assert refused.status_code == 422
    ok = app_client().post("/api/mobile/auth/code/verify", json={"email": "phone-terms@example.com", "code": code, "device": device, "accept_terms": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["terms_accepted"] is True
    [row] = _acceptances(db, "phone-terms@example.com")
    assert (row.channel, row.version) == ("ios", legal.VERSIONS["terms"])
    # Signing in again with the current version on file adds no duplicate row.
    request_code("phone-terms@example.com")
    again = {"email": "phone-terms@example.com", "code": last_code(mailer, "phone-terms@example.com"), "device": device, "accept_terms": True}
    assert app_client().post("/api/mobile/auth/code/verify", json=again).status_code == 200
    assert len(_acceptances(db, "phone-terms@example.com")) == 1


# --- the gates -------------------------------------------------------------------------------


def test_without_current_terms_events_are_closed_but_the_account_stays_yours(
    make_user: Callable[..., User], login_as: Callable[[User], TestClient]
) -> None:
    c = login_as(make_user("old@example.com", terms=False))
    r = c.get("/api/events")
    assert r.status_code == 403 and r.headers["x-required-action"] == "accept-terms"
    me = c.get("/api/me")
    assert me.status_code == 200 and me.json()["terms_accepted"] is False
    # GDPR rights and session control never depend on accepting new terms.
    assert c.get("/api/me/face-consent").status_code == 200
    assert c.delete("/api/me/face-consent").status_code in (200, 204)
    assert c.get("/api/me/devices").status_code == 200
    assert c.patch("/api/me/preferences", json={"theme": "dark"}).status_code == 200
    assert c.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code in (200, 204)


def test_accepting_the_current_version_opens_the_service(
    db: Session, make_user: Callable[..., User], login_as: Callable[[User], TestClient]
) -> None:
    c = login_as(make_user("later@example.com", terms=False))
    stale = c.post("/api/me/legal/accept", json={"document": "terms", "version": "2020-01-01"})
    assert stale.status_code == 409  # was shown an old text
    assert c.get("/api/events").status_code == 403
    ok = c.post("/api/me/legal/accept", json={"document": "terms", "version": legal.VERSIONS["terms"]}, headers={"Accept-Language": "en"})
    assert ok.status_code == 200 and ok.json()["terms_accepted"] is True
    assert c.get("/api/events").status_code == 200
    [row] = _acceptances(db, "later@example.com")
    assert (row.document, row.channel, row.locale) == ("terms", "web", "en")


def test_app_acceptance_is_recorded_as_ios(db: Session, mailer: FakeMailer) -> None:
    from tests.test_mobile_auth import sign_in

    s = sign_in(mailer, "ios-accept@example.com")
    r = s.client.post("/api/me/legal/accept", json={"document": "organizer-terms", "version": legal.VERSIONS["organizer-terms"]})
    assert r.status_code == 200 and r.json()["organizer_terms_accepted"] is True
    assert {(a.document, a.channel) for a in _acceptances(db, "ios-accept@example.com")} == {("terms", "ios"), ("organizer-terms", "ios")}


def test_organizers_must_accept_the_organizer_terms_to_manage(
    db: Session,
    make_user: Callable[..., User],
    make_event: Callable[..., Event],
    add_member: Callable[..., object],
    login_as: Callable[[User], TestClient],
) -> None:
    from app.models import MemberRole

    org = make_user("new-org@example.com", role=UserRole.organizer)
    org.organizer_terms_version = None
    db.commit()
    event = make_event("Gala")
    add_member(event, org, role=MemberRole.organizer)
    c = login_as(org)
    r = c.get(f"/api/events/{event.id}/members")
    assert r.status_code == 403 and r.headers["x-required-action"] == "accept-organizer-terms"
    assert c.get("/api/events").status_code == 200  # attending is unaffected
    assert c.post("/api/me/legal/accept", json={"document": "organizer-terms", "version": legal.VERSIONS["organizer-terms"]}).status_code == 200
    assert c.get(f"/api/events/{event.id}/members").status_code == 200


def test_the_operators_staff_are_not_asked(
    db: Session, make_user: Callable[..., User], make_event: Callable[..., Event], login_as: Callable[[User], TestClient]
) -> None:
    admin = make_user("staff@example.com", role=UserRole.super_admin, terms=False)
    event = make_event("Staff event")
    c = login_as(admin)
    assert c.get("/api/events").status_code == 200
    assert c.get(f"/api/events/{event.id}/members").status_code == 200


def test_acceptances_go_with_the_account(db: Session, mailer: FakeMailer, make_user: Callable[..., User], login_as: Callable[[User], TestClient]) -> None:
    user = make_user("leaving@example.com", terms=False)
    user_id = user.id
    c = login_as(user)
    c.post("/api/me/legal/accept", json={"document": "terms", "version": legal.VERSIONS["terms"]})
    assert len(_acceptances(db, "leaving@example.com")) == 1
    assert c.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code in (200, 204)
    db.expire_all()
    assert db.scalar(select(LegalAcceptance).where(LegalAcceptance.user_id == user_id)) is None
