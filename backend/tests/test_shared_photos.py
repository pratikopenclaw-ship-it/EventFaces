"""Organizer-shared photos: published photos with no face, visible to every member without
a selfie match (services/sharing.py, photo_access.viewable_photos)."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core import storage
from app.core.security import utcnow
from app.models import Face, IndexStatus, MemberRole, Photo, PhotoSource, PhotoStatus, UserRole
from app.services import photo_pipeline
from tests.helpers import group_photo_bytes, solid_jpeg


@pytest.fixture
def w(db: Session, make_user, login_as, make_event, add_member) -> SimpleNamespace:
    event = make_event("Venue Day")
    other = make_event("Other Event")
    org_user = make_user("org@example.com", UserRole.organizer)
    attendee_user = make_user("guest@example.com")
    add_member(event, org_user, role=MemberRole.organizer)
    add_member(other, org_user, role=MemberRole.organizer)
    add_member(event, attendee_user)

    def photo(ev=event, faces: int = 0, status: PhotoStatus = PhotoStatus.published, image: bytes | None = None) -> Photo:
        p = Photo(
            id=uuid.uuid4(),
            event_id=ev.id,
            source=PhotoSource.drive,
            drive_file_id=uuid.uuid4().hex,
            original_filename="venue.jpg",
            status=status,
            index_status=IndexStatus.indexed,
            face_count=faces,
        )
        for variant in ("original", "preview", "thumb"):
            key = storage.photo_key(ev.id, p.id, variant)
            storage.put_jpeg(key, image or solid_jpeg())
            setattr(p, f"{variant}_key", key)
        db.add(p)
        db.commit()
        return p

    return SimpleNamespace(event=event, other=other, org=login_as(org_user), attendee=login_as(attendee_user), photo=photo)


def _share(w: SimpleNamespace, ids: list[uuid.UUID], shared: bool = True):  # type: ignore[no-untyped-def]
    return w.org.post(f"/api/events/{w.event.id}/photos/share", json={"photo_ids": [str(i) for i in ids], "shared": shared})


def _shared_ids(w: SimpleNamespace) -> list[str]:
    r = w.attendee.get(f"/api/events/{w.event.id}/shared-photos")
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()]


def _thumb(w: SimpleNamespace, p: Photo) -> int:
    return w.attendee.get(f"/api/events/{w.event.id}/photos/{p.id}/thumb").status_code


def test_shared_faceless_photo_is_visible_to_every_member(w: SimpleNamespace) -> None:
    p = w.photo()
    assert _thumb(w, p) == 404 and _shared_ids(w) == []  # not matched, not uploaded, not shared

    r = _share(w, [p.id])
    assert r.status_code == 200 and r.json() == {"changed": 1, "skipped": 0}
    assert _shared_ids(w) == [str(p.id)]
    assert _thumb(w, p) == 200
    assert w.attendee.get(f"/api/events/{w.event.id}/photos/{p.id}/preview").status_code == 200
    ticket = w.attendee.post(f"/api/events/{w.event.id}/downloads", json={"photo_ids": [str(p.id)]})
    assert ticket.status_code == 200, ticket.text
    download = w.attendee.get(ticket.json()["url"])
    assert download.status_code == 200 and download.content[:3] == b"\xff\xd8\xff"

    assert _share(w, [p.id], shared=False).json() == {"changed": 1, "skipped": 0}
    assert _thumb(w, p) == 404 and _shared_ids(w) == []


def test_photos_with_faces_unpublished_or_from_another_event_are_never_shared(w: SimpleNamespace, db: Session) -> None:
    counted = w.photo(faces=2)
    pending = w.photo(status=PhotoStatus.pending_review)
    with_face_row = w.photo()  # face_count says 0, but a face row exists: still refused
    db.add(Face(photo_id=with_face_row.id, event_id=w.event.id, bbox=[0, 0, 10, 10], det_score=0.9, embedding=[0.1] * 512))
    db.commit()
    foreign = w.photo(ev=w.other)

    r = _share(w, [counted.id, pending.id, with_face_row.id, foreign.id, uuid.uuid4()])
    assert r.json() == {"changed": 0, "skipped": 5}
    db.expire_all()
    assert all(db.get(Photo, p.id).shared_at is None for p in (counted, pending, with_face_row, foreign))
    assert _shared_ids(w) == []


def test_the_flag_alone_never_exposes_a_photo_with_faces(w: SimpleNamespace, db: Session) -> None:
    """Defence in depth: even a shared_at set outside the sharing service is ignored when
    the photo has faces."""
    p = w.photo(faces=1)
    p.shared_at = utcnow()
    db.commit()
    assert _thumb(w, p) == 404 and _shared_ids(w) == []


def test_reindex_that_finds_faces_unshares_the_photo(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(image=group_photo_bytes())  # people in it, but not detected yet
    assert _share(w, [p.id]).json()["changed"] == 1
    assert photo_pipeline.index_photo(db, p.id) == 6
    db.expire_all()
    assert db.get(Photo, p.id).shared_at is None
    assert _thumb(w, p) == 404 and _shared_ids(w) == []


def test_retired_photo_is_unshared(w: SimpleNamespace, db: Session) -> None:
    p = w.photo()
    _share(w, [p.id])
    assert w.org.delete(f"/api/events/{w.event.id}/photos/{p.id}").status_code == 204
    db.expire_all()
    assert db.get(Photo, p.id).shared_at is None
    assert _shared_ids(w) == []


def test_share_all_faceless_needs_confirmation_and_skips_faces(w: SimpleNamespace, db: Session) -> None:
    a, b = w.photo(), w.photo()
    faced = w.photo(faces=1)
    elsewhere = w.photo(ev=w.other)
    url = f"/api/events/{w.event.id}/photos/share-faceless"

    assert w.org.post(url, json={"confirm_no_people": False}).status_code == 400
    assert _shared_ids(w) == []

    assert w.org.post(url, json={"confirm_no_people": True}).json() == {"changed": 2, "skipped": 0}
    assert sorted(_shared_ids(w)) == sorted([str(a.id), str(b.id)])
    assert w.org.post(url, json={"confirm_no_people": True}).json()["changed"] == 0
    db.expire_all()
    assert db.get(Photo, faced.id).shared_at is None and db.get(Photo, elsewhere.id).shared_at is None


def test_no_sharing_once_retention_deleted_the_face_data(w: SimpleNamespace, db: Session) -> None:
    """After retention every face_count is 0, so "no face" can't be told apart any more."""
    p = w.photo()
    w.event.retention_completed_at = utcnow()
    db.commit()
    assert _share(w, [p.id]).status_code == 409
    assert w.org.post(f"/api/events/{w.event.id}/photos/share-faceless", json={"confirm_no_people": True}).status_code == 409
    assert _share(w, [p.id], shared=False).status_code == 200  # unsharing always works


def test_admin_list_filters_faceless_and_shared(w: SimpleNamespace) -> None:
    a, b = w.photo(), w.photo()
    w.photo(faces=3)
    w.photo(status=PhotoStatus.pending_review)
    _share(w, [a.id])
    base = f"/api/events/{w.event.id}/photos"

    faceless = w.org.get(f"{base}?faceless=true").json()
    assert faceless["total"] == 2 and {i["id"] for i in faceless["items"]} == {str(a.id), str(b.id)}
    shared = w.org.get(f"{base}?faceless=true&shared=true").json()["items"]
    assert [i["id"] for i in shared] == [str(a.id)] and shared[0]["shared_at"] is not None
    assert [i["id"] for i in w.org.get(f"{base}?faceless=true&shared=false").json()["items"]] == [str(b.id)]
