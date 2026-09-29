"""Scheduled retention: biometric data dies with event access; old logs and junk are purged."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.security import hash_token, utcnow
from app.models import (
    AuthToken,
    Face,
    Invite,
    InviteStatus,
    Photo,
    PhotoStatus,
    SearchAudit,
    SearchGrant,
    TokenKind,
    UserRole,
)
from app.services import drive, photo_pipeline
from app.services.retention import run_retention
from app.services.search import FACE_CONSENT_VERSION
from tests.helpers import FakeDrive, half_photo, search_as


def _count(db: Session, model, *where) -> int:  # type: ignore[no-untyped-def]
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@pytest.fixture
def world(make_user, login_as, make_event, add_member, db):
    """Two synced events with faces; an attendee of the first who has matched a photo."""
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    expiring = make_event("Expiring", drive_folder_id="1ExpiringFolderXXXXX", access_expires_at=utcnow() + timedelta(days=1))
    ongoing = make_event("Ongoing", drive_folder_id="1OngoingFolderXXXXXX")
    drive.set_drive_client(
        FakeDrive({expiring.drive_folder_id: {"a": ("a.jpg", half_photo("left"))}, ongoing.drive_folder_id: {"b": ("b.jpg", half_photo("left"))}})
    )
    admin.post(f"/api/events/{expiring.id}/sync")
    admin.post(f"/api/events/{ongoing.id}/sync")

    user = make_user("att@example.com")
    add_member(expiring, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    assert search_as(c, expiring, 0).json()["matches"]
    db.add(Invite(event_id=expiring.id, email="later@example.com", token_hash=hash_token("tok-later-xxxxxx"), expires_at=utcnow() + timedelta(days=5)))
    db.commit()
    return admin, expiring, ongoing


def test_nothing_happens_before_access_ends(world, db: Session) -> None:
    _, expiring, _ = world
    report = run_retention(db)
    assert report.events_expired == 0
    assert _count(db, Face, Face.event_id == expiring.id) == 3


def test_expiry_deletes_faces_grants_and_invites_but_keeps_photos(world, db: Session) -> None:
    _, expiring, ongoing = world
    report = run_retention(db, now=utcnow() + timedelta(days=2))
    assert report.events_expired == 1 and report.faces_deleted == 3 and report.photos_deleted == 0

    db.expire_all()
    assert _count(db, Face, Face.event_id == expiring.id) == 0
    assert _count(db, SearchGrant, SearchGrant.event_id == expiring.id) == 0
    assert db.scalar(select(Invite.status)) == InviteStatus.revoked
    photo = db.scalar(select(Photo).where(Photo.event_id == expiring.id))
    assert photo.status == PhotoStatus.published and storage.head_size(photo.original_key)
    # The other event is untouched
    assert _count(db, Face, Face.event_id == ongoing.id) == 3
    # Idempotent
    assert run_retention(db, now=utcnow() + timedelta(days=2)).events_expired == 0


def test_expiry_can_delete_photos_too(world, db: Session) -> None:
    _, expiring, _ = world
    expiring.delete_photos_on_expiry = True
    db.commit()
    photo = db.scalar(select(Photo).where(Photo.event_id == expiring.id))
    key = photo.original_key

    report = run_retention(db, now=utcnow() + timedelta(days=2))
    assert report.photos_deleted == 1
    db.expire_all()
    assert db.get(Photo, photo.id).status == PhotoStatus.removed
    assert storage.head_size(key) is None


def test_index_job_arriving_after_expiry_does_not_recreate_faces(world, db: Session) -> None:
    _, expiring, _ = world
    photo_id = db.scalar(select(Photo.id).where(Photo.event_id == expiring.id))
    expiring.access_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    run_retention(db)
    assert photo_pipeline.index_photo(db, photo_id) == 0  # e.g. a queued job from before expiry
    assert _count(db, Face, Face.event_id == expiring.id) == 0


def test_extending_access_reindexes(world, db: Session) -> None:
    admin, expiring, _ = world
    expiring.access_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    run_retention(db)
    assert _count(db, Face, Face.event_id == expiring.id) == 0

    new_end = (utcnow() + timedelta(days=30)).isoformat()
    assert admin.patch(f"/api/events/{expiring.id}", json={"access_expires_at": new_end}).status_code == 200
    db.expire_all()
    assert _count(db, Face, Face.event_id == expiring.id) == 3  # Celery runs eagerly in tests
    assert db.get(type(expiring), expiring.id).retention_completed_at is None


def test_housekeeping(make_user, db: Session) -> None:
    now = utcnow()
    stale = make_user("never-verified@example.com", verified=False)
    stale.created_at = now - timedelta(days=30)
    fresh = make_user("just-signed-up@example.com", verified=False)
    keeper = make_user("verified@example.com")
    db.add_all(
        [
            SearchAudit(user_id=keeper.id, match_count=1, created_at=now - timedelta(days=400)),
            SearchAudit(user_id=keeper.id, match_count=2, created_at=now - timedelta(days=10)),
            AuthToken(user_id=keeper.id, kind=TokenKind.refresh, token_hash="a" * 64, expires_at=now - timedelta(days=40)),
            AuthToken(user_id=keeper.id, kind=TokenKind.refresh, token_hash="b" * 64, expires_at=now + timedelta(days=5)),
        ]
    )
    db.commit()

    report = run_retention(db)
    assert report.unverified_users_deleted == 1 and report.audit_rows_deleted == 1 and report.tokens_deleted == 1
    db.expire_all()
    remaining = set(db.scalars(select(type(keeper).email)))
    assert remaining == {fresh.email, keeper.email}
    assert db.scalars(select(SearchAudit.match_count)).all() == [2]
