"""Overflow search queue: when every face-work slot is busy, a search is queued in memory
and the user is told they'll be notified, instead of getting "busy, try again".

Invariants: selfies stay in process memory only (never Redis/disk/storage) and are
dropped after matching; authorization and consent are re-checked when the job runs;
one queued search per user per event; the queue is bounded; the user gets an email
with a link (never photos or counts)."""

import re
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import face_slots
from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import utcnow
from app.models import EventMember, MemberStatus, SearchGrant, User
from app.services import search_queue
from tests.conftest import FakeMailer
from tests.helpers import search_as, selfie_body, selfie_set, solid_jpeg
from tests.test_search import LEFT_PERSON, World, attendee, world  # noqa: F401  (fixture re-export)


@pytest.fixture
def saturated(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], None]]:
    """Every face slot is taken; call the returned function to free it."""
    monkeypatch.setattr(get_settings(), "search_max_concurrent", 1)
    monkeypatch.setattr(get_settings(), "search_queue_wait_seconds", 0.2)
    face_slots.reset()
    search_queue.reset()
    selfie_set(LEFT_PERSON)  # build fixture frames before the clock matters
    assert face_slots.try_acquire_now()
    held = [True]

    def free() -> None:
        if held[0]:
            held[0] = False
            face_slots.release()

    yield free
    free()
    search_queue.stop()
    face_slots.reset()


def _status(c: TestClient, event_id: Any) -> dict[str, Any]:
    r = c.get(f"/api/events/{event_id}/search-status")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _wait_for(c: TestClient, event_id: Any, states: set[str], timeout: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = _status(c, event_id)
        if s["state"] in states:
            return s
        time.sleep(0.2)
    raise AssertionError(f"status never reached {states}: {s}")


def test_busy_search_is_queued_then_completed_and_emailed(
    world: World, attendee: TestClient, saturated: Callable[[], None], db: Session, mailer: FakeMailer  # noqa: F811
) -> None:
    r = search_as(attendee, world.event, LEFT_PERSON)
    assert r.status_code == 202, r.text
    assert r.json()["queued"] is True
    assert _status(attendee, world.event.id)["state"] == "queued"
    user_id = db.scalar(select(User.id).where(User.email == "att@example.com"))
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.user_id == user_id)) == 0

    saturated()  # capacity frees up: the worker picks the job up
    done = _wait_for(attendee, world.event.id, {"done"})
    assert done["match_count"] >= 1
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.user_id == user_id)) >= 1
    # Results are served exactly like a synchronous search's (grants).
    assert len(attendee.get(f"/api/events/{world.event.id}/my-photos").json()) >= 1

    mail = next(m for m in reversed(mailer.outbox) if m.to == "att@example.com")
    assert "ready" in mail.subject.lower()
    assert f"/events/{world.event.id}" in mail.body
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", mail.body.replace(str(world.event.id), "")), "no photo IDs in email"


def test_queued_selfies_never_leave_memory(world: World, attendee: TestClient, saturated: Callable[[], None]) -> None:  # noqa: F811
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    for key in get_redis().scan_iter("*"):
        if get_redis().type(key) == "string":
            value = get_redis().get(key) or ""
            assert len(value) < 1024 and "\\xff\\xd8" not in value and "/9j/" not in value, key
    saturated()
    _wait_for(attendee, world.event.id, {"done"})
    assert search_queue.pending() == 0


def test_one_queued_search_per_user_and_event(world: World, attendee: TestClient, saturated: Callable[[], None]) -> None:  # noqa: F811
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    r = search_as(attendee, world.event, LEFT_PERSON)
    assert r.status_code == 409, r.text


def test_full_queue_answers_busy(world: World, attendee: TestClient, saturated: Callable[[], None], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(get_settings(), "search_overflow_queue_size", 0)
    r = search_as(attendee, world.event, LEFT_PERSON)
    assert r.status_code == 503 and r.headers.get("retry-after")


def test_revoked_before_processing_cancels_the_job(
    world: World, attendee: TestClient, saturated: Callable[[], None], db: Session, mailer: FakeMailer  # noqa: F811
) -> None:
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    user_id = db.scalar(select(User.id).where(User.email == "att@example.com"))
    m = db.get(EventMember, (world.event.id, user_id))
    assert m is not None
    m.status = MemberStatus.revoked
    db.commit()
    saturated()
    deadline = time.monotonic() + 30
    while search_queue.pending() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert search_queue.pending() == 0
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.user_id == user_id)) == 0
    assert not any("ready" in m.subject.lower() for m in mailer.outbox if m.to == "att@example.com")


def test_consent_withdrawn_before_processing_cancels_the_job(
    world: World, attendee: TestClient, saturated: Callable[[], None], db: Session  # noqa: F811
) -> None:
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    assert attendee.delete("/api/me/face-consent").status_code == 200
    saturated()
    s = _wait_for(attendee, world.event.id, {"cancelled", "none"})
    assert s["state"] in ("cancelled", "none")
    user_id = db.scalar(select(User.id).where(User.email == "att@example.com"))
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.user_id == user_id)) == 0


def test_rejected_selfie_in_queue_reports_the_reason(
    world: World, attendee: TestClient, saturated: Callable[[], None], mailer: FakeMailer  # noqa: F811
) -> None:
    token = attendee.post(f"/api/events/{world.event.id}/capture-token").json()["token"]
    blank = solid_jpeg(size=(640, 480))
    body, headers = selfie_body([("front", blank), ("left", blank), ("right", blank)])
    headers["x-capture-token"] = token
    assert attendee.post(f"/api/events/{world.event.id}/search?source=camera", content=body, headers=headers).status_code == 202
    saturated()
    s = _wait_for(attendee, world.event.id, {"rejected"})
    assert s["message"] and s["shot"] == "front"
    mail = next(m for m in reversed(mailer.outbox) if m.to == "att@example.com")
    assert "try again" in mail.body.lower()


def test_lost_job_is_reported_as_expired(world: World, attendee: TestClient, saturated: Callable[[], None], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """A server restart loses queued selfies (by design: memory only). The status then
    tells the user to search again instead of waiting forever."""
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    search_queue.stop()  # what a restart does: worker gone, in-memory queue gone
    monkeypatch.setattr(search_queue, "now", lambda: utcnow() + timedelta(seconds=get_settings().search_queue_ttl_seconds + 1))
    assert _status(attendee, world.event.id)["state"] == "expired"
    # And the user may search again right away.
    saturated()
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200


def test_status_is_private_to_its_owner(world: World, attendee: TestClient, saturated: Callable[[], None], make_user, login_as, add_member) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    other = make_user("other-member@example.com")
    add_member(world.event, other)
    assert _status(login_as(other), world.event.id)["state"] == "none"
    outsider = login_as(make_user("outsider2@example.com"))
    assert outsider.get(f"/api/events/{world.event.id}/search-status").status_code == 403


def test_my_events_shows_the_search_state(world: World, attendee: TestClient, saturated: Callable[[], None]) -> None:  # noqa: F811
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    ev = next(e for e in attendee.get("/api/events").json() if e["id"] == str(world.event.id))
    assert ev["search_state"] == "queued"
    saturated()
    _wait_for(attendee, world.event.id, {"done"})
    ev = next(e for e in attendee.get("/api/events").json() if e["id"] == str(world.event.id))
    assert ev["search_state"] == "done"


def test_account_deletion_forgets_search_state(world: World, attendee: TestClient, saturated: Callable[[], None]) -> None:  # noqa: F811
    from tests.conftest import PASSWORD

    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 202
    assert attendee.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code == 200
    assert not list(get_redis().scan_iter("searchjob:*"))
    saturated()
    deadline = time.monotonic() + 30
    while search_queue.pending() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert search_queue.pending() == 0


def test_queue_memory_is_bounded_in_bytes(world: World, attendee: TestClient, saturated: Callable[[], None], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(get_settings(), "search_queue_max_bytes", 10_000)  # smaller than one selfie set
    r = search_as(attendee, world.event, LEFT_PERSON)
    assert r.status_code == 503, r.text
    assert search_queue.pending() == 0
