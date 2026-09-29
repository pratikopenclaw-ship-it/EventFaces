"""Drive import → thumbnails → face indexing, driven through the API with a fake Drive.

Celery runs eagerly in tests, so POST /sync executes the whole pipeline inline.
"""

import io
from datetime import timedelta

import pytest
from celery.exceptions import Retry
from PIL import Image
from sqlalchemy import func, select

from app.core import storage
from app.core.config import get_settings
from app.core.security import utcnow
from app.models import DriveSyncRun, Face, IndexStatus, MemberRole, Photo, PhotoStatus, SyncStatus, UserRole
from app.services import drive
from tests.helpers import FakeDrive, group_photo_bytes, solid_jpeg

FOLDER = "1FolderAAAAAAAAAAAAA"
OTHER_FOLDER = "1FolderBBBBBBBBBBBBB"


@pytest.fixture
def organizer(make_user, login_as, make_event, add_member):
    """(client, event) for an organizer of an event linked to FOLDER."""
    user = make_user("org@example.com", UserRole.organizer)
    event = make_event("Gala", drive_folder_id=FOLDER)
    add_member(event, user, role=MemberRole.organizer)
    return login_as(user), event


def _photos(db, event_id):
    db.expire_all()
    return db.scalars(select(Photo).where(Photo.event_id == event_id).order_by(Photo.original_filename)).all()


def test_sync_imports_indexes_and_dedupes(organizer, db) -> None:
    client, event = organizer
    fake = FakeDrive({FOLDER: {"f1": ("group.jpg", group_photo_bytes()), "f2": ("sky.jpg", solid_jpeg())}})
    drive.set_drive_client(fake)

    r = client.post(f"/api/events/{event.id}/sync")
    assert r.status_code == 202, r.text

    photos = _photos(db, event.id)
    assert [p.original_filename for p in photos] == ["group.jpg", "sky.jpg"]
    assert all(p.index_status == IndexStatus.indexed and p.status == PhotoStatus.published for p in photos)
    group, sky = photos
    assert group.face_count == 6 and sky.face_count == 0

    # stored variants exist, are JPEGs, and live under this event's prefix
    for key in (group.original_key, group.preview_key, group.thumb_key):
        assert key and key.startswith(f"events/{event.id}/")
        assert Image.open(io.BytesIO(storage.get_bytes(key))).format == "JPEG"

    # one embedding row per face, tagged with the photo's event
    faces = db.scalars(select(Face).where(Face.photo_id == group.id)).all()
    assert len(faces) == 6
    assert all(f.event_id == event.id and len(f.embedding) == 512 for f in faces)

    status = client.get(f"/api/events/{event.id}/sync").json()
    assert status["last_run"]["status"] == "completed"
    assert status["last_run"]["files_listed"] == 2 and status["last_run"]["files_new"] == 2
    assert status["pipeline"]["indexed"] == 2 and not status["in_progress"]
    assert status["published_photos"] == 2 and status["faces"] == 6
    assert status["service_account_email"].endswith("iam.gserviceaccount.com")

    # second sync: nothing new is downloaded again
    fake.downloads.clear()
    assert client.post(f"/api/events/{event.id}/sync").status_code == 202
    assert fake.downloads == []
    last = client.get(f"/api/events/{event.id}/sync").json()["last_run"]
    assert last["files_listed"] == 2 and last["files_new"] == 0
    assert len(_photos(db, event.id)) == 2

    # event list shows the photo count
    assert client.get("/api/events").json()[0]["photo_count"] == 2


def test_sync_paginates(organizer, db) -> None:
    client, event = organizer
    files = {f"f{i}": (f"p{i}.jpg", solid_jpeg((i * 20, 50, 50))) for i in range(5)}
    drive.set_drive_client(FakeDrive({FOLDER: files}, page_size=2))
    client.post(f"/api/events/{event.id}/sync")
    assert len(_photos(db, event.id)) == 5


def test_new_files_are_picked_up_on_resync(organizer, db) -> None:
    client, event = organizer
    folder = {"f1": ("a.jpg", solid_jpeg())}
    fake = FakeDrive({FOLDER: folder})
    drive.set_drive_client(fake)
    client.post(f"/api/events/{event.id}/sync")

    folder["f2"] = ("b.jpg", solid_jpeg((1, 2, 3)))
    fake.downloads.clear()
    client.post(f"/api/events/{event.id}/sync")
    assert fake.downloads == ["f2"]
    assert len(_photos(db, event.id)) == 2


def test_bad_file_is_rejected_and_not_retried(organizer, db) -> None:
    client, event = organizer
    fake = FakeDrive({FOLDER: {"bad": ("notes.jpg", b"this is not an image"), "ok": ("ok.jpg", solid_jpeg())}})
    drive.set_drive_client(fake)
    client.post(f"/api/events/{event.id}/sync")

    bad, ok = _photos(db, event.id)
    assert bad.index_status == IndexStatus.failed and bad.status == PhotoStatus.rejected
    assert "JPEG, PNG and HEIC" in (bad.error or "")
    assert ok.status == PhotoStatus.published

    fake.downloads.clear()
    client.post(f"/api/events/{event.id}/sync")
    assert fake.downloads == []  # rejected files are not re-downloaded
    assert client.get(f"/api/events/{event.id}/sync").json()["published_photos"] == 1


def test_transient_import_error_schedules_retry(organizer, monkeypatch) -> None:
    client, event = organizer
    fake = FakeDrive({FOLDER: {"f1": ("a.jpg", solid_jpeg())}})
    drive.set_drive_client(fake)

    def network_down(*_args: object) -> bytes:
        raise ConnectionError("network down")

    monkeypatch.setattr(fake, "download", network_down)
    with pytest.raises(Retry):  # eager Celery surfaces the scheduled retry as an exception
        client.post(f"/api/events/{event.id}/sync")


def test_exhausted_retries_fail_photo_then_next_sync_retries_it(organizer, db, monkeypatch) -> None:
    client, event = organizer
    fake = FakeDrive({FOLDER: {"f1": ("a.jpg", solid_jpeg())}})
    drive.set_drive_client(fake)
    real_download = fake.download

    def network_down(*_args: object) -> bytes:
        raise ConnectionError("network down")

    monkeypatch.setattr(fake, "download", network_down)
    monkeypatch.setattr("app.workers.tasks.MAX_RETRIES", 0)  # simulate the final attempt
    client.post(f"/api/events/{event.id}/sync")
    (photo,) = _photos(db, event.id)
    assert photo.index_status == IndexStatus.failed and photo.status == PhotoStatus.processing
    assert "network down" in (photo.error or "")

    monkeypatch.setattr(fake, "download", real_download)
    client.post(f"/api/events/{event.id}/sync")
    (photo,) = _photos(db, event.id)
    assert photo.index_status == IndexStatus.indexed and photo.status == PhotoStatus.published
    assert client.get(f"/api/events/{event.id}/sync").json()["last_run"]["files_retried"] == 1


def test_unshared_folder_fails_run_with_helpful_error(organizer) -> None:
    client, event = organizer
    drive.set_drive_client(FakeDrive({OTHER_FOLDER: {}}))
    client.post(f"/api/events/{event.id}/sync")
    run = client.get(f"/api/events/{event.id}/sync").json()["last_run"]
    assert run["status"] == "failed"
    assert "isn't shared with" in run["error"]


def test_sync_requires_folder_and_config(make_user, login_as, make_event, monkeypatch) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    no_folder = make_event("No Folder")
    assert admin.post(f"/api/events/{no_folder.id}/sync").status_code == 400

    linked = make_event("Linked", drive_folder_id=FOLDER)
    monkeypatch.setattr(get_settings(), "google_service_account_json", "")
    assert admin.post(f"/api/events/{linked.id}/sync").status_code == 503


def test_concurrent_sync_rejected_but_stale_run_does_not_block(organizer, db) -> None:
    client, event = organizer
    drive.set_drive_client(FakeDrive({FOLDER: {}}))
    run = DriveSyncRun(event_id=event.id, folder_id=FOLDER, status=SyncStatus.running)
    db.add(run)
    db.commit()
    assert client.post(f"/api/events/{event.id}/sync").status_code == 409

    run.created_at = utcnow() - timedelta(hours=3)  # crashed worker left it "running"
    db.commit()
    assert client.post(f"/api/events/{event.id}/sync").status_code == 202


def test_sync_and_photo_endpoints_require_organizer(make_user, login_as, make_event, add_member, db) -> None:
    other_org = make_user("other-org@example.com", UserRole.organizer)
    attendee = make_user("att@example.com")
    event = make_event("Gala", drive_folder_id=FOLDER)
    other_event = make_event("Other")
    add_member(other_event, other_org, role=MemberRole.organizer)
    add_member(event, attendee)
    drive.set_drive_client(FakeDrive({FOLDER: {"f1": ("a.jpg", solid_jpeg())}}))

    for c in (login_as(other_org), login_as(attendee)):
        assert c.post(f"/api/events/{event.id}/sync").status_code == 403
        assert c.get(f"/api/events/{event.id}/sync").status_code == 403
        assert c.get(f"/api/events/{event.id}/photos").status_code == 403
    assert login_as(attendee).get("/api/drive/service-account").status_code == 403


def test_admin_image_endpoint_is_event_scoped(make_user, login_as, make_event, add_member, db) -> None:
    org_user = make_user("org@example.com", UserRole.organizer)
    mine = make_event("Mine", drive_folder_id=FOLDER)
    theirs = make_event("Theirs", drive_folder_id=OTHER_FOLDER)
    add_member(mine, org_user, role=MemberRole.organizer)
    drive.set_drive_client(
        FakeDrive({FOLDER: {"a": ("a.jpg", solid_jpeg())}, OTHER_FOLDER: {"b": ("b.jpg", solid_jpeg((9, 9, 9)))}})
    )
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    admin.post(f"/api/events/{mine.id}/sync")
    admin.post(f"/api/events/{theirs.id}/sync")
    (my_photo,) = _photos(db, mine.id)
    (their_photo,) = _photos(db, theirs.id)

    org = login_as(org_user)
    listed = org.get(f"/api/events/{mine.id}/photos").json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == str(my_photo.id)

    r = org.get(f"/api/events/{mine.id}/photos/{my_photo.id}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff"
    assert "location" not in r.headers  # streamed by the API, not a redirect to storage

    # Pairing my event ID with another event's photo ID must not leak it.
    assert org.get(f"/api/events/{mine.id}/photos/{their_photo.id}/thumb").status_code == 404
    assert org.get(f"/api/events/{theirs.id}/photos/{their_photo.id}/thumb").status_code == 403


def test_deleting_event_removes_photos_faces_and_objects(make_user, login_as, make_event, db) -> None:
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    event = make_event("Doomed", drive_folder_id=FOLDER)
    drive.set_drive_client(FakeDrive({FOLDER: {"g": ("group.jpg", group_photo_bytes())}}))
    event_id = event.id
    admin.post(f"/api/events/{event_id}/sync")
    prefix = storage.event_prefix(event_id)
    s3 = storage.get_s3()
    assert s3.list_objects_v2(Bucket=get_settings().s3_bucket, Prefix=prefix).get("KeyCount") == 3

    assert admin.delete(f"/api/events/{event_id}").status_code == 204
    assert db.scalar(select(func.count()).select_from(Face).where(Face.event_id == event_id)) == 0
    assert db.scalar(select(func.count()).select_from(Photo).where(Photo.event_id == event_id)) == 0
    assert s3.list_objects_v2(Bucket=get_settings().s3_bucket, Prefix=prefix).get("KeyCount") == 0
