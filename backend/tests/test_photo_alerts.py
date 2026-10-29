"""New-photo alerts (Part 1): tell attendees who searched an event that new photos went live.
Nothing biometric is stored (docs/superpowers/specs/2026-10-20-new-photo-alerts-design.md)."""

import re
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core import storage
from app.core.security import utcnow
from app.models import EventPhotoAlert, IndexStatus, MemberRole, ModerationMode, Photo, PhotoSource, PhotoStatus, UserRole
from app.services import photo_pipeline
from app.services.search import FACE_CONSENT_VERSION
from tests.helpers import group_photo_bytes, search_as, solid_jpeg

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def w(db: Session, make_user, login_as, make_event, add_member) -> SimpleNamespace:
    event = make_event("Summer Party", guest_upload_enabled=True, moderation_mode=ModerationMode.manual)
    org_user = make_user("org@example.com", UserRole.organizer)
    attendee_user = make_user("guest@example.com")
    add_member(event, org_user, role=MemberRole.organizer)
    add_member(event, attendee_user)

    def photo(status: PhotoStatus = PhotoStatus.processing, image: bytes | None = None, faces: int = 0) -> Photo:
        p = Photo(
            id=uuid.uuid4(),
            event_id=event.id,
            source=PhotoSource.drive,
            drive_file_id=uuid.uuid4().hex,
            original_filename="party.jpg",
            status=status,
            index_status=IndexStatus.queued,
            face_count=faces,
        )
        for variant in ("original", "preview", "thumb"):
            key = storage.photo_key(event.id, p.id, variant)
            storage.put_jpeg(key, image or solid_jpeg())
            setattr(p, f"{variant}_key", key)
        db.add(p)
        db.commit()
        return p

    attendee = login_as(attendee_user)
    attendee.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    return SimpleNamespace(event=event, org=login_as(org_user), attendee=attendee, attendee_user=attendee_user, photo=photo)


def _search(w: SimpleNamespace) -> None:
    r = search_as(w.attendee, w.event)
    assert r.status_code == 200, r.text


def _row(db: Session, w: SimpleNamespace) -> EventPhotoAlert | None:
    db.expire_all()
    return db.get(EventPhotoAlert, (w.attendee_user.id, w.event.id))


def _banner(w: SimpleNamespace) -> bool:
    r = w.attendee.get(f"/api/events/{w.event.id}")
    assert r.status_code == 200, r.text
    return r.json()["new_photos_since_last_search"]


# --- Task 1: published_at -------------------------------------------------------------


def test_index_publishes_with_published_at(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(image=group_photo_bytes())
    assert photo_pipeline.index_photo(db, p.id) == 6
    db.expire_all()
    photo = db.get(Photo, p.id)
    assert photo.status == PhotoStatus.published
    assert photo.published_at is not None and abs(utcnow() - photo.published_at) < timedelta(seconds=5)


def test_moderation_approval_sets_published_at(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(status=PhotoStatus.pending_review)
    r = w.org.post(f"/api/events/{w.event.id}/photos/{p.id}/moderate", json={"action": "approve"})
    assert r.status_code == 204, r.text
    db.expire_all()
    photo = db.get(Photo, p.id)
    assert photo.status == PhotoStatus.published and photo.published_at is not None


def test_reindex_keeps_published_at(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(image=group_photo_bytes())
    photo_pipeline.index_photo(db, p.id)
    db.expire_all()
    first = db.get(Photo, p.id).published_at
    photo_pipeline.index_photo(db, p.id)  # e.g. reindex-faces after a model change
    db.expire_all()
    assert db.get(Photo, p.id).published_at == first


def test_only_publish_helper_sets_published() -> None:
    """Every transition to published goes through photo_pipeline.publish, so published_at
    (what alerts batch on) can't be missed by a future path."""
    pattern = re.compile(r"\.status\s*=\s*PhotoStatus\.published\b|status=PhotoStatus\.published\b")
    hits = [
        (path.relative_to(APP).as_posix(), n)
        for path in APP.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert len(hits) == 1 and hits[0][0] == "services/photo_pipeline.py", hits
    source = (APP / "services/photo_pipeline.py").read_text().splitlines()
    body = source[source.index("def publish(photo: Photo) -> None:") :][:6]
    assert any(pattern.search(line) for line in body)


# --- Task 2: subscribe on search, toggles, banner flag ----------------------------------


def test_search_records_subscription(w: SimpleNamespace, db: Session) -> None:
    assert _row(db, w) is None
    _search(w)
    row = _row(db, w)
    assert row is not None and row.enabled and abs(utcnow() - row.last_searched_at) < timedelta(seconds=30)
    first = row.last_searched_at
    assert w.attendee.put(f"/api/events/{w.event.id}/photo-alerts", json={"enabled": False}).status_code == 200
    _search(w)
    row = _row(db, w)
    assert row.last_searched_at > first and row.enabled is False  # a new search keeps the opt-out


def test_banner_flag(w: SimpleNamespace, db: Session) -> None:
    assert _banner(w) is False  # never searched
    _search(w)
    assert _banner(w) is False
    w.photo(image=solid_jpeg())  # faceless photos never count
    photo_pipeline.index_photo(db, w.photo(image=solid_jpeg()).id)
    assert _banner(w) is False
    photo_pipeline.index_photo(db, w.photo(image=group_photo_bytes()).id)
    assert _banner(w) is True
    _search(w)
    assert _banner(w) is False


def test_toggle_requires_prior_search(w: SimpleNamespace) -> None:
    url = f"/api/events/{w.event.id}/photo-alerts"
    assert w.attendee.get(url).json() == {"subscribed": False, "enabled": False}
    r = w.attendee.put(url, json={"enabled": False})
    assert r.status_code == 409 and r.json()["detail"] == "search_first"


def test_toggle_roundtrip(w: SimpleNamespace) -> None:
    url = f"/api/events/{w.event.id}/photo-alerts"
    _search(w)
    assert w.attendee.get(url).json() == {"subscribed": True, "enabled": True}
    assert w.attendee.put(url, json={"enabled": False}).json() == {"subscribed": True, "enabled": False}
    assert w.attendee.get(url).json() == {"subscribed": True, "enabled": False}
    assert w.attendee.put(url, json={"enabled": True}).json() == {"subscribed": True, "enabled": True}


def test_preferences_new_photo_alerts(w: SimpleNamespace, db: Session) -> None:
    assert w.attendee.get("/api/me").json()["new_photo_alerts"] is True
    r = w.attendee.patch("/api/me/preferences", json={"new_photo_alerts": False})
    assert r.status_code == 200 and r.json()["new_photo_alerts"] is False
    assert not [h for h in r.headers.get_list("set-cookie") if h.startswith("ef_theme=")]  # theme untouched
    assert r.json()["theme"] == "system"
    r = w.attendee.patch("/api/me/preferences", json={"theme": "dark"})
    assert r.json()["theme"] == "dark" and r.json()["new_photo_alerts"] is False


def test_admin_event_out_has_no_alert_rows(w: SimpleNamespace) -> None:
    """Organizers never see who searched (Privacy Notice): no alert data in admin views."""
    _search(w)
    admin = w.org.get(f"/api/events/{w.event.id}/admin").json()
    members = w.org.get(f"/api/events/{w.event.id}/members").json()
    text = str(admin) + str(members)
    for field in ("last_searched_at", "new_photos_since_last_search", "notified_through", "last_notified_at", "subscribed"):
        assert field not in text


def test_organizer_can_disable_notify_new_photos(w: SimpleNamespace) -> None:
    assert w.org.get(f"/api/events/{w.event.id}/admin").json()["notify_new_photos"] is True
    r = w.org.patch(f"/api/events/{w.event.id}", json={"notify_new_photos": False})
    assert r.status_code == 200 and r.json()["notify_new_photos"] is False
