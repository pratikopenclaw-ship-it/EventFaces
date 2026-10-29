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
from app.models import IndexStatus, MemberRole, ModerationMode, Photo, PhotoSource, PhotoStatus, UserRole
from app.services import photo_pipeline
from tests.helpers import group_photo_bytes, solid_jpeg

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

    return SimpleNamespace(
        event=event, org=login_as(org_user), attendee=login_as(attendee_user), attendee_user=attendee_user, photo=photo
    )


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
