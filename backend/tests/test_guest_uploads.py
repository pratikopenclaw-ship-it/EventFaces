"""Guest uploads (presigned PUT → validate → ingest → index), moderation, reports, admin delete."""

import io
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.db import SessionLocal
from app.models import Event, Face, MemberRole, ModerationMode, Photo, PhotoReport, PhotoStatus, SearchGrant, UserRole
from app.services import photo_pipeline
from app.services.search import FACE_CONSENT_VERSION
from tests.helpers import half_photo, jpeg_with_gps, png_bytes, search_as

LEFT_PERSON = 0


@pytest.fixture
def setup(make_user, login_as, make_event, add_member):
    """(event, uploader client, searcher client, organizer client) for a guest-upload event."""

    def _make(moderation: ModerationMode = ModerationMode.auto, enabled: bool = True, prefix: str = ""):
        event = make_event("Wedding", guest_upload_enabled=enabled, moderation_mode=moderation)
        uploader_user = make_user(f"{prefix}guest@example.com")
        searcher_user = make_user(f"{prefix}searcher@example.com")
        org_user = make_user(f"{prefix}org@example.com", UserRole.organizer)
        add_member(event, uploader_user)
        add_member(event, searcher_user)
        add_member(event, org_user, role=MemberRole.organizer)
        searcher = login_as(searcher_user)
        searcher.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
        return event, login_as(uploader_user), searcher, login_as(org_user)

    return _make


def upload(client: TestClient, event: Event, data: bytes, content_type: str = "image/jpeg", declared: int | None = None):
    """Run the whole browser flow: start → PUT to presigned URL → complete."""
    r = client.post(
        f"/api/events/{event.id}/uploads",
        json={"filename": "IMG_0001.jpg", "content_type": content_type, "size": declared or len(data)},
    )
    assert r.status_code == 201, r.text
    start = r.json()
    put = httpx.put(start["upload_url"], content=data, headers={"content-type": content_type})
    return start, put, client.post(f"/api/events/{event.id}/uploads/{start['photo_id']}/complete")


def _search(client: TestClient, event: Event) -> list[str]:
    r = search_as(client, event, LEFT_PERSON)
    assert r.status_code == 200, r.text
    return [m["id"] for m in r.json()["matches"]]


def test_auto_moderated_upload_is_stripped_indexed_and_searchable(setup, db: Session) -> None:
    event, uploader, searcher, _ = setup(ModerationMode.auto)
    start, put, done = upload(uploader, event, jpeg_with_gps(half_photo("left")))
    assert put.status_code == 200 and done.status_code == 200, done.text
    pid = uuid.UUID(start["photo_id"])

    photo = db.get(Photo, pid)
    assert photo.status == PhotoStatus.published and photo.face_count == 3
    assert photo.upload_key is None  # raw upload deleted after ingest
    assert storage.head_size(storage.upload_key(event.id, pid)) is None
    original = storage.get_bytes(photo.original_key)
    assert b"SecretCam" not in original and len(Image.open(io.BytesIO(original)).getexif()) == 0

    assert _search(searcher, event) == [str(pid)]
    mine = uploader.get(f"/api/events/{event.id}/my-uploads").json()
    assert [(u["id"], u["status"]) for u in mine] == [(str(pid), "published")]
    assert str(pid) in {p["id"] for p in uploader.get(f"/api/events/{event.id}/my-photos").json()}


def test_manual_moderation_hides_photo_until_approved(setup, db: Session) -> None:
    event, uploader, searcher, org = setup(ModerationMode.manual)
    start, _, done = upload(uploader, event, half_photo("left"))
    assert done.json()["status"] == "pending_review"
    pid = start["photo_id"]

    # Indexed (so approval is instant) but invisible everywhere
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == uuid.UUID(pid))) == 3
    assert _search(searcher, event) == []
    assert uploader.get(f"/api/events/{event.id}/my-photos").json() == []
    assert uploader.get(f"/api/events/{event.id}/photos/{pid}/thumb").status_code == 404

    queue = org.get(f"/api/events/{event.id}/moderation").json()
    assert [q["id"] for q in queue] == [pid] and queue[0]["uploader_email"] == "guest@example.com"
    assert org.post(f"/api/events/{event.id}/photos/{pid}/moderate", json={"action": "approve"}).status_code == 204
    assert _search(searcher, event) == [pid]
    assert org.get(f"/api/events/{event.id}/moderation").json() == []


def test_rejecting_deletes_faces_and_files(setup, db: Session) -> None:
    event, uploader, searcher, org = setup(ModerationMode.manual)
    start, _, _ = upload(uploader, event, half_photo("left"))
    pid = uuid.UUID(start["photo_id"])
    keys = [getattr(db.get(Photo, pid), k) for k in ("original_key", "preview_key", "thumb_key")]

    assert org.post(f"/api/events/{event.id}/photos/{pid}/moderate", json={"action": "reject"}).status_code == 204
    db.expire_all()
    assert db.get(Photo, pid).status == PhotoStatus.rejected
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == pid)) == 0
    assert all(storage.head_size(k) is None for k in keys)
    assert _search(searcher, event) == []
    assert org.post(f"/api/events/{event.id}/photos/{pid}/moderate", json={"action": "approve"}).status_code == 409
    assert uploader.get(f"/api/events/{event.id}/my-uploads").json()[0]["status"] == "rejected"


def test_upload_permissions_and_declared_limits(setup, make_user, login_as) -> None:
    event, uploader, _, _ = setup(enabled=False, prefix="disabled-")
    body = {"filename": "a.jpg", "content_type": "image/jpeg", "size": 1000}
    assert uploader.post(f"/api/events/{event.id}/uploads", json=body).status_code == 403

    event, uploader, _, _ = setup()
    outsider = login_as(make_user("outsider@example.com"))
    assert outsider.post(f"/api/events/{event.id}/uploads", json=body).status_code == 403
    assert uploader.post(f"/api/events/{event.id}/uploads", json={**body, "content_type": "image/gif"}).status_code == 415
    assert uploader.post(f"/api/events/{event.id}/uploads", json={**body, "size": 26 * 1024 * 1024}).status_code == 413


def test_presigned_url_is_locked_to_declared_size_and_type(setup) -> None:
    event, uploader, _, _ = setup()
    data = half_photo("left")
    _, put, done = upload(uploader, event, data, declared=len(data) - 100)
    assert put.status_code == 403  # storage refuses a different size than signed
    assert done.status_code == 409  # nothing arrived

    r = uploader.post(f"/api/events/{event.id}/uploads", json={"filename": "a.jpg", "content_type": "image/jpeg", "size": len(data)})
    put = httpx.put(r.json()["upload_url"], content=data, headers={"content-type": "text/html"})
    assert put.status_code == 403  # nor a different content type


@pytest.mark.parametrize(
    ("payload", "declared_type"),
    [(b"<html><script>alert(1)</script></html>" + b" " * 200, "image/jpeg"), (png_bytes(), "image/jpeg")],
    ids=["html-as-jpeg", "png-as-jpeg"],
)
def test_magic_bytes_checked_on_complete(setup, db: Session, payload: bytes, declared_type: str) -> None:
    event, uploader, _, _ = setup()
    start, put, done = upload(uploader, event, payload, content_type=declared_type)
    assert put.status_code == 200 and done.status_code == 415
    pid = uuid.UUID(start["photo_id"])
    db.expire_all()
    assert db.get(Photo, pid).status == PhotoStatus.rejected
    assert storage.head_size(storage.upload_key(event.id, pid)) is None  # raw object removed


def test_complete_is_single_use_and_owner_only(setup, make_user, login_as, add_member) -> None:
    event, uploader, searcher, _ = setup()
    data = half_photo("right")
    r = uploader.post(f"/api/events/{event.id}/uploads", json={"filename": "a.jpg", "content_type": "image/jpeg", "size": len(data)})
    start = r.json()
    assert uploader.post(f"/api/events/{event.id}/uploads/{start['photo_id']}/complete").status_code == 409  # not PUT yet
    httpx.put(start["upload_url"], content=data, headers={"content-type": "image/jpeg"})
    assert searcher.post(f"/api/events/{event.id}/uploads/{start['photo_id']}/complete").status_code == 404
    assert uploader.post(f"/api/events/{event.id}/uploads/{start['photo_id']}/complete").status_code == 200
    assert uploader.post(f"/api/events/{event.id}/uploads/{start['photo_id']}/complete").status_code == 409


def test_admin_delete_revokes_everything(setup, db: Session) -> None:
    event, uploader, searcher, org = setup()
    start, _, _ = upload(uploader, event, half_photo("left"))
    pid = start["photo_id"]
    assert _search(searcher, event) == [pid]
    ticket = searcher.post(f"/api/events/{event.id}/downloads", json={"photo_ids": [pid]}).json()["url"]

    assert org.delete(f"/api/events/{event.id}/photos/{pid}").status_code == 204
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.photo_id == uuid.UUID(pid))) == 0
    assert _search(searcher, event) == []
    assert searcher.get(ticket).status_code == 403  # an already-issued link stops working
    assert searcher.get(f"/api/events/{event.id}/photos/{pid}/thumb").status_code == 404
    assert org.get(f"/api/events/{event.id}/photos/{pid}/thumb").status_code == 404
    assert uploader.delete(f"/api/events/{event.id}/photos/{pid}").status_code == 403  # attendees can't delete


def test_reports(setup, make_user, login_as, add_member, db: Session) -> None:
    event, uploader, searcher, org = setup()
    start, _, _ = upload(uploader, event, half_photo("left"))
    pid = start["photo_id"]
    _search(searcher, event)

    bystander_user = make_user("bystander@example.com")
    add_member(event, bystander_user)
    bystander = login_as(bystander_user)
    body = {"reason": "its_me_remove", "details": "Please remove, I'm in this"}
    assert bystander.post(f"/api/events/{event.id}/photos/{pid}/report", json=body).status_code == 404  # can't see it
    assert searcher.post(f"/api/events/{event.id}/photos/{pid}/report", json=body).status_code == 201
    assert searcher.post(f"/api/events/{event.id}/photos/{pid}/report", json=body).status_code == 201  # deduped
    assert uploader.post(f"/api/events/{event.id}/photos/{pid}/report", json={"reason": "other"}).status_code == 201

    reports = org.get(f"/api/events/{event.id}/reports").json()
    assert len(reports) == 2 and {r["reporter_email"] for r in reports} == {"searcher@example.com", "guest@example.com"}
    assert searcher.get(f"/api/events/{event.id}/reports").status_code == 403

    rid = next(r["id"] for r in reports if r["reporter_email"] == "guest@example.com")
    assert org.post(f"/api/events/{event.id}/reports/{rid}/resolve", json={"action": "dismiss"}).status_code == 204
    rid = org.get(f"/api/events/{event.id}/reports").json()[0]["id"]
    assert org.post(f"/api/events/{event.id}/reports/{rid}/resolve", json={"action": "remove_photo"}).status_code == 204
    db.expire_all()
    assert db.get(Photo, uuid.UUID(pid)).status == PhotoStatus.removed
    assert org.get(f"/api/events/{event.id}/reports").json() == []
    statuses = sorted(r.status.value for r in db.scalars(select(PhotoReport)))
    assert statuses == ["dismissed", "photo_removed"]


def test_indexing_never_writes_faces_for_a_photo_retired_mid_job(setup, db: Session, monkeypatch) -> None:
    """Race: an organizer rejects a photo while its indexing job is running."""
    event, uploader, _, _ = setup(ModerationMode.manual)
    start, _, _ = upload(uploader, event, half_photo("left"))
    pid = uuid.UUID(start["photo_id"])
    real_detect = photo_pipeline.detect_faces

    def detect_then_reject(img):  # type: ignore[no-untyped-def]
        faces = real_detect(img)
        with SessionLocal() as other:  # the organizer's request, in its own transaction
            photo = other.get(Photo, pid, with_for_update=True)
            photo_pipeline.retire_photo(other, photo, PhotoStatus.rejected)
            other.commit()
        return faces

    monkeypatch.setattr(photo_pipeline, "detect_faces", detect_then_reject)
    assert photo_pipeline.index_photo(db, pid) == 0
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == pid)) == 0
    assert db.get(Photo, pid).status == PhotoStatus.rejected


def test_abandoned_uploads_are_hidden_then_cleaned_up(setup, db: Session) -> None:
    from datetime import timedelta

    from app.core.security import utcnow

    event, uploader, _, _ = setup()
    data = half_photo("left")
    r = uploader.post(f"/api/events/{event.id}/uploads", json={"filename": "a.jpg", "content_type": "image/jpeg", "size": len(data)})
    start = r.json()
    httpx.put(start["upload_url"], content=data, headers={"content-type": "image/jpeg"})  # PUT ok, never completed
    pid = uuid.UUID(start["photo_id"])
    assert uploader.get(f"/api/events/{event.id}/my-uploads").json() == []

    assert photo_pipeline.cleanup_abandoned_uploads(db) == 0  # URL could still be used
    db.get(Photo, pid).created_at = utcnow() - timedelta(hours=3)
    db.commit()
    assert photo_pipeline.cleanup_abandoned_uploads(db) == 1
    db.expire_all()
    assert db.get(Photo, pid) is None
    assert storage.head_size(storage.upload_key(event.id, pid)) is None
