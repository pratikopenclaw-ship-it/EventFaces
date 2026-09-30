"""Face-search abuse: per-event scraping ceiling (SEC-024) and 'selfies/embeddings are never
persisted' checked in the places test_search.py doesn't cover: logs, Redis, DB schema."""

import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis import get_redis
from app.services.search import FACE_CONSENT_VERSION
from tests.helpers import search_as
from tests.test_search import LEFT_PERSON, World, attendee, world  # noqa: F401  (fixture re-export)


def _consenting_member(make_user, login_as, add_member, event, email: str) -> TestClient:  # type: ignore[no-untyped-def]
    user = make_user(email)
    add_member(event, user)
    c = login_as(user)
    assert c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION}).status_code == 200
    return c


def test_search_has_a_per_event_ceiling(world: World, make_user, login_as, add_member, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    """Many accounts in one event (sybil scraping) can't multiply the per-user limit."""
    monkeypatch.setattr(get_settings(), "search_rate_limit", "5/600")
    monkeypatch.setattr(get_settings(), "search_event_rate_limit", "3/600")
    clients = [_consenting_member(make_user, login_as, add_member, world.event, f"sybil{i}@example.com") for i in range(4)]
    codes = [search_as(c, world.event, LEFT_PERSON).status_code for c in clients]
    assert codes == [200, 200, 200, 429]


def test_search_logs_contain_no_selfie_or_embedding(world: World, attendee: TestClient, caplog: pytest.LogCaptureFixture) -> None:  # noqa: F811
    caplog.set_level(logging.DEBUG)
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200
    blob = "\n".join(f"{r.getMessage()} {r.args!r} {getattr(r, '__dict__', {})!r}" for r in caplog.records)
    assert "\\xff\\xd8" not in blob and "/9j/" not in blob, "JPEG bytes (raw or base64) in logs"
    assert not re.search(r"(-?\d\.\d{3,}[, ]+){16,}", blob), "a float vector (embedding?) in logs"


def test_search_leaves_nothing_biometric_in_redis(world: World, attendee: TestClient) -> None:  # noqa: F811
    r = get_redis()
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200
    for key in r.scan_iter("*"):
        kind = r.type(key)
        if kind != "string":
            continue
        value = r.get(key) or ""
        assert len(value) < 512, (key, len(value))
        assert not re.search(r"(-?\d\.\d{3,}[, ]+){16,}", value), key


def test_only_the_faces_table_stores_vectors_and_nothing_stores_blobs(db: Session) -> None:
    rows = db.execute(
        text(
            """
            SELECT c.table_name, c.column_name, c.udt_name
            FROM information_schema.columns c
            WHERE c.table_schema = 'public' AND c.udt_name IN ('vector', 'bytea', 'halfvec', 'sparsevec')
            """
        )
    ).all()
    assert [(t, col, u) for t, col, u in rows] == [("faces", "embedding", "vector")]


def test_rejected_requests_do_not_burn_the_event_budget(world: World, make_user, login_as, add_member, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    monkeypatch.setattr(get_settings(), "search_rate_limit", "50/600")
    monkeypatch.setattr(get_settings(), "search_event_rate_limit", "2/600")
    griefer = _consenting_member(make_user, login_as, add_member, world.event, "griefer@example.com")
    for _ in range(5):  # no capture token → 403 each time
        assert griefer.post(f"/api/events/{world.event.id}/search?source=camera", content=b"x").status_code == 403
    honest = [_consenting_member(make_user, login_as, add_member, world.event, f"honest{i}@example.com") for i in range(2)]
    assert [search_as(c, world.event, LEFT_PERSON).status_code for c in honest] == [200, 200]


def test_selfie_pixel_bomb_is_refused_without_decoding(world: World, attendee: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """SEC-025 through the API: a 32 KB PNG declaring 144 MP."""
    import io
    import time

    from PIL import Image

    from app.models import Event

    monkeypatch.setattr(get_settings(), "allow_selfie_file_upload", True)
    event = db.get(Event, world.event.id)
    assert event is not None
    event.allow_selfie_file_upload = True
    db.commit()
    buf = io.BytesIO()
    Image.new("1", (12000, 12000), 1).save(buf, format="PNG", optimize=True)
    t = time.monotonic()
    r = attendee.post(f"/api/events/{world.event.id}/search?source=upload", content=buf.getvalue(), headers={"content-type": "image/png"})
    assert r.status_code == 422 and r.json()["code"] == "unreadable", r.text
    assert time.monotonic() - t < 1.0
