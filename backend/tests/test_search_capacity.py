"""SEC-039: face work is capped per process. Beyond the cap a request waits briefly for a
slot, then gets 503 + Retry-After, *before* its selfie body is read (so queued requests
hold no image memory) and without spending the user's search budget."""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import selfie as selfie_module
from app.core import face_slots
from app.core.config import get_settings
from tests.conftest import FakeMailer, new_client
from tests.helpers import search_as, selfie_of
from tests.test_privacy import _start_removal, two_events  # noqa: F401  (fixture re-export)
from tests.test_search import LEFT_PERSON, World, attendee, world  # noqa: F401  (fixture re-export)


@pytest.fixture
def one_slot(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "search_max_concurrent", 1)
    monkeypatch.setattr(get_settings(), "search_queue_wait_seconds", 0.3)
    # These tests cover the "turned away" path, which since the overflow queue exists
    # applies when the queue is full or disabled (tests/test_search_queue.py covers queuing).
    monkeypatch.setattr(get_settings(), "search_overflow_queue_size", 0)
    face_slots.reset()
    yield
    face_slots.reset()


@pytest.fixture
def body_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    for name in ("read_selfie", "read_selfie_set"):
        original = getattr(selfie_module, name)

        async def spy(*a, _o=original, _n=name, **k):  # type: ignore[no-untyped-def]
            seen.append(_n)
            return await _o(*a, **k)

        from app.api.routes import privacy, search

        for mod in (selfie_module, search, privacy):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, spy)
    return seen


def test_search_beyond_capacity_is_503_fast_without_reading_the_body(
    world: World, attendee: TestClient, one_slot: None, body_reads: list[str]  # noqa: F811
) -> None:
    from tests.helpers import selfie_set

    selfie_set(LEFT_PERSON)  # build the fixture frames now, outside the timed window
    assert face_slots.try_acquire_now()  # another request is doing face work
    try:
        t = time.monotonic()
        r = search_as(attendee, world.event, LEFT_PERSON)
        assert r.status_code == 503, r.text
        assert r.headers.get("retry-after", "").isdigit()
        assert time.monotonic() - t < 3
        assert body_reads == [], "a request that can't be served must not buffer its selfies"
    finally:
        face_slots.release()
    # The busy response didn't spend the search budget, and the slot is usable again.
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200


def test_slots_are_released_after_success_and_rejection(world: World, attendee: TestClient, one_slot: None) -> None:  # noqa: F811
    for _ in range(3):
        assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200
    # A quality-gate rejection (422) must release its slot too.
    token = attendee.post(f"/api/events/{world.event.id}/capture-token").json()["token"]
    from tests.helpers import selfie_body, solid_jpeg

    body, headers = selfie_body([("front", solid_jpeg(size=(640, 480))), ("left", solid_jpeg(size=(640, 480))), ("right", solid_jpeg(size=(640, 480)))])
    headers["x-capture-token"] = token
    assert attendee.post(f"/api/events/{world.event.id}/search?source=camera", content=body, headers=headers).status_code == 422
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200


def test_a_request_waits_briefly_for_a_slot_before_giving_up(world: World, attendee: TestClient, one_slot: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    import threading

    monkeypatch.setattr(get_settings(), "search_queue_wait_seconds", 5)
    assert face_slots.try_acquire_now()
    threading.Timer(0.5, face_slots.release).start()  # the other search finishes shortly
    assert search_as(attendee, world.event, LEFT_PERSON).status_code == 200


def test_removal_submit_shares_the_cap(two_events, mailer: FakeMailer, one_slot: None, body_reads: list[str]) -> None:  # noqa: F811
    a, _, _ = two_events
    token = _start_removal(mailer, a.slug)
    assert face_slots.try_acquire_now()
    try:
        r = new_client().post(f"/api/removal-requests/{token}/submit", content=selfie_of(0), headers={"content-type": "image/jpeg"})
        assert r.status_code == 503 and body_reads == []
    finally:
        face_slots.release()
    r = new_client().post(f"/api/removal-requests/{token}/submit", content=selfie_of(0), headers={"content-type": "image/jpeg"})
    assert r.status_code == 200, r.text


def test_default_cap_is_bounded_and_positive() -> None:
    s = get_settings()
    assert 2 <= s.search_max_concurrent <= 64
    assert 0 <= s.search_queue_wait_seconds <= 30


def test_waiting_for_a_slot_holds_no_db_connection(world: World, attendee: TestClient, one_slot: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Queued requests must not park pooled connections (that was SEC-038's failure mode)."""
    from app.core.db import engine

    baseline = engine.pool.checkedout()
    seen: list[int] = []
    original = face_slots._acquire

    async def spy(wait: float) -> bool:
        seen.append(engine.pool.checkedout() - baseline)
        return await original(wait)

    monkeypatch.setattr(face_slots, "_acquire", spy)
    assert face_slots.try_acquire_now()
    try:
        assert search_as(attendee, world.event, LEFT_PERSON).status_code == 503
    finally:
        face_slots.release()
    assert seen == [0], seen
