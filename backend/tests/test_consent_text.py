"""The consent text is versioned: users agree to one exact wording. Changing a word without
bumping FACE_CONSENT_VERSION would treat old consents as consent to new text."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.models import User
from app.services import consent_text
from app.services.search import FACE_CONSENT_VERSION

# version -> fingerprint of the exact text users consent to. Edit both together.
PINNED = {"2026-09-30": "c0dc72e3c4c8320963067f73f21841ca565c9760a1c669918155d59d63980ae7"}


def test_text_changes_require_a_new_consent_version() -> None:
    assert FACE_CONSENT_VERSION in PINNED, "new consent version: pin its fingerprint here"
    assert consent_text.fingerprint() == PINNED[FACE_CONSENT_VERSION], (
        "The consent text changed: bump FACE_CONSENT_VERSION (everyone is asked again) and pin the new fingerprint"
    )


@pytest.mark.parametrize(
    ("header", "locale"),
    [(None, "en"), ("de-DE,de;q=0.9,en;q=0.8", "de"), ("fr-FR,de;q=0.5", "de"), ("fr-FR", "en"), ("EN-us", "en"), ("*", "en")],
)
def test_language_follows_accept_language(header: str | None, locale: str, make_user: Callable[..., User], login_as: Callable[..., TestClient]) -> None:
    c = login_as(make_user(f"lang-{locale}-{abs(hash(header))}@example.com"))
    r = c.get("/api/me/face-consent", headers={"Accept-Language": header} if header else {})
    text = r.json()["text"]
    assert text["locale"] == locale
    assert len(text["sections"]) == 4 and all(s["paragraphs"] for s in text["sections"])


def test_both_languages_say_the_same_things() -> None:
    en, de = consent_text.consent_text("en", 7), consent_text.consent_text("de", 7)
    assert [len(s.paragraphs) for s in en.sections] == [len(s.paragraphs) for s in de.sections]
    for t in (en, de):
        flat = " ".join(p for s in t.sections for p in s.paragraphs)
        assert "7" in flat and "{grant_days}" not in flat  # retention period filled in
        assert "15" in flat  # queue wait disclosed
        assert "9" in flat  # Art. 9(2)(a) GDPR legal basis
