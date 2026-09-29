"""Match tiers, 3-shot merging, match feedback, anonymization and the threshold dashboard."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Event, FeedbackVerdict, MatchFeedback, MemberRole, SearchGrant, UserRole
from app.services import drive
from app.services.feedback import Band, suggest_threshold
from app.services.retention import run_retention
from app.services.search import FACE_CONSENT_VERSION, Match, merge_best
from tests.helpers import FakeDrive, half_photo, search_as

P0 = 0


@pytest.fixture
def world(make_user, login_as, make_event, add_member):
    event = make_event("Party", drive_folder_id="1FeedbackFolderXXXXX")
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    drive.set_drive_client(FakeDrive({event.drive_folder_id: {"l": ("left.jpg", half_photo("left")), "r": ("right.jpg", half_photo("right"))}}))
    admin.post(f"/api/events/{event.id}/sync")
    user = make_user("att@example.com")
    add_member(event, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    org_user = make_user("org@example.com", UserRole.organizer)
    add_member(event, org_user, role=MemberRole.organizer)
    return event, user, c, login_as(org_user), admin


def test_merge_best_keeps_highest_similarity_per_photo() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    merged = merge_best([[Match(a, 0.5), Match(b, 0.7)], [Match(a, 0.8)], [Match(b, 0.6)]])
    assert [(m.photo_id, m.similarity) for m in merged] == [(a, 0.8), (b, 0.7)]


def test_results_have_tiers_and_search_id(world, monkeypatch) -> None:
    event, _, c, _, _ = world
    r = search_as(c, event, P0).json()
    assert isinstance(r["search_id"], int) and [q["shot"] for q in r["quality"]] == ["front", "left", "right"]
    assert r["matches"][0]["tier"] == "best"  # same-photo selfie: very high similarity

    monkeypatch.setattr(get_settings(), "match_best_threshold", 0.999)
    r = search_as(c, event, P0).json()
    assert r["matches"][0]["tier"] == "possible"


def test_feedback_stored_without_biometric_data(world, db: Session) -> None:
    event, user, c, _, _ = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    assert c.post(f"/api/events/{event.id}/feedback", json={"photo_id": photo_id, "verdict": "me"}).status_code == 204

    fb = db.scalar(select(MatchFeedback))
    grant = db.scalar(select(SearchGrant))
    # Values come from the server-side grant, not the client
    assert (fb.user_id, fb.photo_id, fb.face_id, fb.search_id) == (user.id, uuid.UUID(photo_id), grant.face_id, grant.search_id)
    assert fb.similarity_score == pytest.approx(grant.similarity) and fb.verdict == FeedbackVerdict.me
    # Schema-level guarantee: no image or embedding columns
    columns = {col["name"]: str(col["type"]) for col in inspect(db.get_bind()).get_columns("match_feedback")}
    assert set(columns) == {"id", "search_id", "user_id", "event_id", "photo_id", "face_id", "similarity_score", "verdict", "created_at"}
    assert not any("VECTOR" in t.upper() or "BYTEA" in t.upper() for t in columns.values())

    # Changing your mind updates the single row
    c.post(f"/api/events/{event.id}/feedback", json={"photo_id": photo_id, "verdict": "not_me"})
    db.expire_all()
    assert [f.verdict for f in db.scalars(select(MatchFeedback))] == [FeedbackVerdict.not_me]


def test_not_me_hides_the_photo_now_and_in_later_searches(world, db: Session) -> None:
    event, _, c, _, _ = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    c.post(f"/api/events/{event.id}/feedback", json={"photo_id": photo_id, "verdict": "not_me"})
    assert c.get(f"/api/events/{event.id}/my-photos").json() == []
    assert c.get(f"/api/events/{event.id}/photos/{photo_id}/thumb").status_code == 404
    assert photo_id not in {m["id"] for m in search_as(c, event, P0).json()["matches"]}


def test_cannot_rate_photos_you_were_not_shown(world, make_user, login_as, add_member) -> None:
    event, _, c, _, _ = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    other = make_user("other@example.com")
    add_member(event, other)
    oc = login_as(other)
    assert oc.post(f"/api/events/{event.id}/feedback", json={"photo_id": photo_id, "verdict": "me"}).status_code == 404
    assert c.post(f"/api/events/{event.id}/feedback", json={"photo_id": str(uuid.uuid4()), "verdict": "me"}).status_code == 404


def test_missing_report(world, db: Session) -> None:
    event, user, c, _, _ = world
    search_id = search_as(c, event, P0).json()["search_id"]
    assert c.post(f"/api/events/{event.id}/feedback/missing").status_code == 204
    fb = db.scalar(select(MatchFeedback))
    assert fb.verdict == FeedbackVerdict.missing and fb.photo_id is None and fb.search_id == search_id
    codes = [c.post(f"/api/events/{event.id}/feedback/missing").status_code for _ in range(3)]
    assert codes[-1] == 429


def _rated(db: Session) -> MatchFeedback:
    db.expire_all()
    return db.scalar(select(MatchFeedback))


def _assert_anonymized(fb: MatchFeedback) -> None:
    assert (fb.user_id, fb.photo_id, fb.face_id, fb.search_id) == (None, None, None, None)
    assert fb.similarity_score is not None and fb.verdict == FeedbackVerdict.me and fb.event_id is not None


def _rate_me(c, event) -> None:  # type: ignore[no-untyped-def]
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    c.post(f"/api/events/{event.id}/feedback", json={"photo_id": photo_id, "verdict": "me"})


def test_anonymized_on_consent_withdrawal(world, db: Session) -> None:
    event, _, c, _, _ = world
    _rate_me(c, event)
    c.delete("/api/me/face-consent")
    _assert_anonymized(_rated(db))


def test_anonymized_on_account_deletion(world, db: Session) -> None:
    from tests.conftest import PASSWORD

    event, _, c, _, _ = world
    _rate_me(c, event)
    assert c.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code == 200
    _assert_anonymized(_rated(db))


def test_anonymized_when_event_face_data_expires(world, db: Session) -> None:
    event, _, c, _, _ = world
    _rate_me(c, event)
    db.get(Event, event.id).access_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert run_retention(db).feedback_anonymized == 1
    _assert_anonymized(_rated(db))


# --- Dashboard / threshold suggestion ------------------------------------------------------


def _bands(counts: dict[float, tuple[int, int]]) -> list[Band]:
    """{band lower edge: (me, not_me)} → Band list from 0.30 to 1.00."""
    out, lower = [], 0.30
    while lower < 0.999:
        me, not_me = counts.get(round(lower, 2), (0, 0))
        out.append(Band(round(lower, 2), round(lower + 0.05, 2), me, not_me))
        lower += 0.05
    return out


def test_suggestion_needs_enough_feedback() -> None:
    t, note = suggest_threshold(_bands({0.5: (5, 1)}))
    assert t is None and "Not enough" in note


def test_suggestion_picks_lowest_cutoff_meeting_precision() -> None:
    bands = _bands({0.35: (2, 8), 0.40: (4, 6), 0.45: (9, 1), 0.50: (10, 0), 0.60: (10, 0)})
    t, _ = suggest_threshold(bands)
    # ≥0.45: 29/30 = 97% ✓ ; ≥0.40: 33/40 = 82% ✗
    assert t == 0.45


def test_suggestion_none_when_precision_never_reached() -> None:
    t, note = suggest_threshold(_bands({0.5: (10, 10), 0.7: (5, 5)}))
    assert t is None and "raising" in note


def test_dashboard_endpoints(world, make_user, login_as, add_member) -> None:
    event, _, c, org, admin = world
    _rate_me(c, event)
    c.post(f"/api/events/{event.id}/feedback/missing")

    q = org.get(f"/api/events/{event.id}/match-quality").json()
    assert q["searches"] == 1 and q["feedback"] == 1 and q["missing_reports"] == 1
    assert sum(b["me"] for b in q["bands"]) == 1 and q["shots_total"] == 3 and q["shots_passed"] == 3
    assert sum(q["quality_histogram"]) == 3 and q["suggested_threshold"] is None

    assert c.get(f"/api/events/{event.id}/match-quality").status_code == 403  # attendees can't
    g = admin.get("/api/admin/match-quality").json()
    assert [e["event_name"] for e in g["events"]] == ["Party"] and g["events"][0]["wrong_rate"] == 0.0
    assert org.get("/api/admin/match-quality").status_code == 403
