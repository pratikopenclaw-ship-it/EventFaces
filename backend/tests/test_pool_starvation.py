"""SEC-038: face analysis (seconds of CPU, serialized behind the model lock) must never run
while the request holds a database connection or row lock. Otherwise ~15 concurrent
selfie searches exhaust the connection pool and every other endpoint 500s (found by the
k6 load test: `QueuePool limit of size 5 overflow 10 reached` on /capture-token)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import engine
from app.services import faces
from tests.conftest import FakeMailer, new_client
from tests.helpers import search_as, selfie_of
from tests.test_privacy import _start_removal, two_events  # noqa: F401  (fixture re-export)
from tests.test_search import LEFT_PERSON, World, attendee, world  # noqa: F401  (fixture re-export)


@pytest.fixture
def connections_during_face_work(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Pool connections checked out each time the face model runs, minus the baseline."""
    seen: list[int] = []
    baseline = engine.pool.checkedout()
    for name in ("analyze_selfie", "detect_faces"):
        original = getattr(faces, name)

        def spy(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
            seen.append(engine.pool.checkedout() - baseline)
            return _original(*args, **kwargs)

        monkeypatch.setattr(faces, name, spy)
        # Modules that imported the function directly.
        from app.services import search, selfie_quality

        for mod in (search, selfie_quality):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, spy)
    return seen


def test_search_holds_no_db_connection_during_face_analysis(
    world: World, attendee: TestClient, connections_during_face_work: list[int]  # noqa: F811
) -> None:
    r = search_as(attendee, world.event, LEFT_PERSON)
    assert r.status_code == 200, r.text
    assert connections_during_face_work, "the face model was never called"
    assert set(connections_during_face_work) == {0}, connections_during_face_work


def test_removal_submit_holds_no_db_connection_during_face_analysis(
    two_events, mailer: FakeMailer, connections_during_face_work: list[int], db: Session  # noqa: F811
) -> None:
    a, _, _ = two_events
    token = _start_removal(mailer, a.slug)
    connections_during_face_work.clear()
    r = new_client().post(f"/api/removal-requests/{token}/submit", content=selfie_of(0), headers={"content-type": "image/jpeg"})
    assert r.status_code == 200, r.text
    assert connections_during_face_work, "the face model was never called"
    assert set(connections_during_face_work) == {0}, connections_during_face_work


def test_removal_submit_twice_concurrently_submits_once(two_events, mailer: FakeMailer) -> None:  # noqa: F811
    """Releasing the row lock during face work must not allow a double submit."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    a, _, _ = two_events
    token = _start_removal(mailer, a.slug)
    barrier = Barrier(4)

    def go() -> int:
        c = new_client()
        barrier.wait()
        return c.post(f"/api/removal-requests/{token}/submit", content=selfie_of(0), headers={"content-type": "image/jpeg"}).status_code

    with ThreadPoolExecutor(4) as pool:
        codes = sorted(pool.map(lambda _: go(), range(4)))
    assert codes.count(200) == 1 and all(c in (200, 404, 410) for c in codes), codes
