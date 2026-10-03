"""Selfie search: end-to-end flow, event isolation, privacy, and download authorization."""

import io
import tempfile
import uuid
import zipfile
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import get_settings
from app.models import (
    Event,
    Face,
    MemberRole,
    MemberStatus,
    Photo,
    PhotoStatus,
    SearchAudit,
    SearchGrant,
    UserRole,
)
from app.services import drive
from app.services.search import FACE_CONSENT_VERSION, search_faces, selfie_embedding
from tests.helpers import FakeDrive, group_photo_bytes, half_photo, search_as, selfie_body, selfie_of, selfie_set, solid_jpeg

LEFT_PERSON, RIGHT_PERSON = 0, 5  # indexes into group_faces(), sorted left→right


@dataclass
class World:
    admin: TestClient
    event: Event
    photos: dict[str, uuid.UUID]  # filename → photo id


@pytest.fixture
def world(make_user, login_as, make_event, db) -> World:
    """An event whose Drive folder has: left half (3 people), right half (3 others), a sky photo."""
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    event = make_event("Party", drive_folder_id="1PartyFolderXXXXXXX")
    return World(admin, event, _sync(admin, event, db, {"left.jpg": half_photo("left"), "right.jpg": half_photo("right"), "sky.jpg": solid_jpeg()}))


def _sync(admin: TestClient, event: Event, db: Session, files: dict[str, bytes]) -> dict[str, uuid.UUID]:
    folder = event.drive_folder_id or ""
    existing = getattr(drive, "_override", None)
    folders = dict(existing.folders) if isinstance(existing, FakeDrive) else {}
    folders[folder] = {f"{event.id}-{name}": (name, data) for name, data in files.items()}
    drive.set_drive_client(FakeDrive(folders))
    assert admin.post(f"/api/events/{event.id}/sync").status_code == 202
    db.expire_all()
    return {p.original_filename or "": p.id for p in db.scalars(select(Photo).where(Photo.event_id == event.id))}


@pytest.fixture
def attendee(make_user, login_as, add_member, world):
    """A verified attendee of `world.event` who has consented to face search."""
    user = make_user("att@example.com")
    add_member(world.event, user)
    client = login_as(user)
    assert client.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION}).status_code == 200
    return client


def _upload(client: TestClient, event: Event, body: bytes, content_type: str = "image/jpeg"):  # type: ignore[no-untyped-def]
    return client.post(f"/api/events/{event.id}/search?source=upload", content=body, headers={"content-type": content_type})


# --- End-to-end -------------------------------------------------------------------


def test_end_to_end_search_gallery_and_download(world: World, attendee: TestClient, db: Session) -> None:
    ev, photos = world.event, world.photos

    r = search_as(attendee, ev, LEFT_PERSON)
    assert r.status_code == 200, r.text
    matches = r.json()["matches"]
    assert [m["id"] for m in matches] == [str(photos["left.jpg"])]
    assert matches[0]["similarity"] >= get_settings().face_match_threshold

    r = search_as(attendee, ev, RIGHT_PERSON)
    assert [m["id"] for m in r.json()["matches"]] == [str(photos["right.jpg"])]

    # Gallery remembers both matches (until the grant expires)
    gallery = {p["id"] for p in attendee.get(f"/api/events/{ev.id}/my-photos").json()}
    assert gallery == {str(photos["left.jpg"]), str(photos["right.jpg"])}

    # Thumbnails of matched photos are viewable; the unmatched one is not
    assert attendee.get(f"/api/events/{ev.id}/photos/{photos['left.jpg']}/preview").status_code == 200
    assert attendee.get(f"/api/events/{ev.id}/photos/{photos['sky.jpg']}/thumb").status_code == 404

    # Single download
    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [str(photos["left.jpg"])]})
    assert r.status_code == 200
    file = attendee.get(r.json()["url"])
    assert file.status_code == 200 and file.content[:3] == b"\xff\xd8\xff"
    assert 'filename="left.jpg"' in file.headers["content-disposition"]

    # Download all as ZIP
    ids = [str(photos["left.jpg"]), str(photos["right.jpg"])]
    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": ids})
    archive = attendee.get(r.json()["url"])
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        assert sorted(zf.namelist()) == ["left.jpg", "right.jpg"]
        assert zf.read("left.jpg")[:3] == b"\xff\xd8\xff"

    # Audit log: one row per search with the match count, nothing else
    rows = db.scalars(select(SearchAudit).order_by(SearchAudit.id)).all()
    assert [(r.event_id, r.match_count) for r in rows] == [(ev.id, 1), (ev.id, 1)]


def test_no_match_returns_empty_and_is_audited(world: World, make_user, login_as, add_member, db) -> None:
    stranger = make_user("stranger@example.com")
    add_member(world.event, stranger)
    c = login_as(stranger)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    # Remove the left photo: that person's face now appears nowhere searchable in this event
    db.get(Photo, world.photos["left.jpg"]).status = PhotoStatus.removed
    db.commit()
    r = search_as(c, world.event, LEFT_PERSON)
    assert r.status_code == 200 and r.json()["matches"] == []
    assert db.scalar(select(SearchAudit.match_count).where(SearchAudit.user_id == stranger.id)) == 0


# --- Event isolation (non-negotiable) ------------------------------------------------


def test_selfie_never_returns_photos_from_another_event(world: World, make_user, login_as, add_member, make_event, db) -> None:
    """The *same* photo exists in events A and B. A user who belongs to both searches in A:
    only A's copy may come back, even though B's copy is a perfect match."""
    event_a = world.event
    event_b = make_event("Other Party", drive_folder_id="1OtherFolderXXXXXXX")
    b_photos = _sync(world.admin, event_b, db, {"left.jpg": half_photo("left")})

    user = make_user("both@example.com")
    add_member(event_a, user)
    add_member(event_b, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})

    found_a = {m["id"] for m in search_as(c, event_a, LEFT_PERSON).json()["matches"]}
    assert found_a == {str(world.photos["left.jpg"])}
    assert str(b_photos["left.jpg"]) not in found_a

    found_b = {m["id"] for m in search_as(c, event_b, LEFT_PERSON).json()["matches"]}
    assert found_b == {str(b_photos["left.jpg"])}

    # Grants are per event too
    grants = db.execute(select(SearchGrant.photo_id, SearchGrant.event_id).where(SearchGrant.user_id == user.id)).all()
    assert set(grants) == {(world.photos["left.jpg"], event_a.id), (b_photos["left.jpg"], event_b.id)}

    # And the photo endpoint of event A won't serve B's photo even though the user may see it in B
    assert c.get(f"/api/events/{event_a.id}/photos/{b_photos['left.jpg']}/thumb").status_code == 404


def test_member_of_one_event_cannot_search_another(world: World, make_user, login_as, add_member, make_event, db) -> None:
    event_b = make_event("Private", drive_folder_id="1PrivateFolderXXXXX")
    _sync(world.admin, event_b, db, {"g.jpg": group_photo_bytes()})
    user = make_user("a-only@example.com")
    add_member(world.event, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    assert search_as(c, event_b, LEFT_PERSON).status_code == 403


def test_search_faces_is_always_event_scoped(world: World, make_event, db) -> None:
    event_b = make_event("B", drive_folder_id="1BFolderXXXXXXXXXXX")
    b_photos = _sync(world.admin, event_b, db, {"g.jpg": group_photo_bytes()})
    emb = selfie_embedding(selfie_of(LEFT_PERSON))

    found = search_faces(db, event_id=world.event.id, embedding=emb, threshold=0.0, limit=1000)
    returned = {m.photo_id for m in found}
    assert returned <= set(world.photos.values())
    assert b_photos["g.jpg"] not in returned

    with pytest.raises(TypeError):
        search_faces(db, emb, 0.4, 10)  # type: ignore[misc]  # event_id can't be passed positionally
    with pytest.raises(ValueError):
        search_faces(db, event_id=None, embedding=emb, threshold=0.4, limit=10)  # type: ignore[arg-type]


@pytest.mark.parametrize("hidden", [PhotoStatus.processing, PhotoStatus.pending_review, PhotoStatus.rejected, PhotoStatus.removed])
def test_unpublished_photos_never_match(world: World, attendee: TestClient, db: Session, hidden: PhotoStatus) -> None:
    db.get(Photo, world.photos["left.jpg"]).status = hidden
    db.commit()
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == world.photos["left.jpg"])) == 3
    assert search_as(attendee, world.event, LEFT_PERSON).json()["matches"] == []


# --- Consent ------------------------------------------------------------------------


def test_consent_required_and_withdrawable(world: World, make_user, login_as, add_member, db) -> None:
    user = make_user("new@example.com")
    add_member(world.event, user)
    c = login_as(user)
    info = c.get("/api/me/face-consent").json()
    text = info.pop("text")  # the versioned consent text (tests/test_consent_text.py)
    assert info == {"version": FACE_CONSENT_VERSION, "grant_days": 7, "given": False, "given_at": None}
    assert text["locale"] == "en" and text["title"] == "Before we look for you"

    r = search_as(c, world.event, LEFT_PERSON)  # the capture token is refused without consent
    assert r.status_code == 403 and r.json()["detail"] == "consent_required"
    assert c.post("/api/me/face-consent", json={"version": "old-version"}).status_code == 409
    assert c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION}).json()["given"] is True

    assert search_as(c, world.event, LEFT_PERSON).json()["matches"]
    assert c.get(f"/api/events/{world.event.id}/my-photos").json()

    # Withdrawing forgets results: grants gone, gallery empty, photos no longer viewable
    assert c.delete("/api/me/face-consent").json()["given"] is False
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.user_id == user.id)) == 0
    assert c.get(f"/api/events/{world.event.id}/my-photos").json() == []
    assert c.get(f"/api/events/{world.event.id}/photos/{world.photos['left.jpg']}/thumb").status_code == 404
    assert search_as(c, world.event, LEFT_PERSON).status_code == 403


# --- Input validation ------------------------------------------------------------------


def test_file_upload_needs_global_switch_and_event_setting(world: World, attendee: TestClient, db: Session, monkeypatch) -> None:
    ev = world.event
    front = selfie_set(LEFT_PERSON)[0][1]
    assert _upload(attendee, ev, front).status_code == 403  # both off (defaults)

    db.get(Event, ev.id).allow_selfie_file_upload = True
    db.commit()
    assert _upload(attendee, ev, front).status_code == 403  # event allows, global switch off

    monkeypatch.setattr(get_settings(), "allow_selfie_file_upload", True)
    r = _upload(attendee, ev, front)
    assert r.status_code == 200 and [m["id"] for m in r.json()["matches"]] == [str(world.photos["left.jpg"])]

    db.get(Event, ev.id).allow_selfie_file_upload = False
    db.commit()
    assert _upload(attendee, ev, front).status_code == 403  # global on, event off


def test_upload_selfie_validation(world: World, attendee: TestClient, db: Session, monkeypatch) -> None:
    ev = world.event
    db.get(Event, ev.id).allow_selfie_file_upload = True
    db.commit()
    monkeypatch.setattr(get_settings(), "allow_selfie_file_upload", True)

    r = _upload(attendee, ev, solid_jpeg(size=(800, 600)))
    assert r.status_code == 422 and r.json()["code"] == "no_face"
    assert _upload(attendee, ev, b"GIF89a not really").json()["code"] == "unreadable"
    assert _upload(attendee, ev, selfie_set(LEFT_PERSON)[0][1], content_type="application/pdf").status_code == 415
    monkeypatch.setattr(get_settings(), "selfie_max_bytes", 1000)
    assert _upload(attendee, ev, selfie_set(LEFT_PERSON)[0][1]).status_code == 413


def test_camera_search_requires_fresh_single_use_token(world: World, attendee: TestClient) -> None:
    ev = world.event
    body, headers = selfie_body(selfie_set(LEFT_PERSON))
    url = f"/api/events/{ev.id}/search?source=camera"

    assert attendee.post(url, content=body, headers=headers).json()["detail"] == "capture_token_invalid"
    assert attendee.post(url, content=body, headers={**headers, "x-capture-token": "made-up-token-123"}).status_code == 403

    token = attendee.post(f"/api/events/{ev.id}/capture-token").json()["token"]
    assert attendee.post(url, content=body, headers={**headers, "x-capture-token": token}).status_code == 200
    assert attendee.post(url, content=body, headers={**headers, "x-capture-token": token}).status_code == 403  # reused

    # A single image isn't a camera search
    token = attendee.post(f"/api/events/{ev.id}/capture-token").json()["token"]
    r = attendee.post(url, content=selfie_set(LEFT_PERSON)[0][1], headers={"content-type": "image/jpeg", "x-capture-token": token})
    assert r.status_code == 400


def test_capture_token_is_bound_to_user_and_event(world: World, attendee: TestClient, make_user, login_as, add_member, make_event) -> None:
    ev = world.event
    other_user = make_user("other@example.com")
    add_member(ev, other_user)
    other = login_as(other_user)
    other.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    stolen = attendee.post(f"/api/events/{ev.id}/capture-token").json()["token"]
    body, headers = selfie_body(selfie_set(LEFT_PERSON))
    r = other.post(f"/api/events/{ev.id}/search?source=camera", content=body, headers={**headers, "x-capture-token": stolen})
    assert r.status_code == 403


def test_expired_capture_token(world: World, attendee: TestClient, monkeypatch) -> None:
    from app.core.redis import get_redis

    ev = world.event
    token = attendee.post(f"/api/events/{ev.id}/capture-token").json()["token"]
    for key in get_redis().scan_iter("captok:*"):
        get_redis().delete(key)  # what Redis does after 60 s
    body, headers = selfie_body(selfie_set(LEFT_PERSON))
    r = attendee.post(f"/api/events/{ev.id}/search?source=camera", content=body, headers={**headers, "x-capture-token": token})
    assert r.status_code == 403


def test_search_is_rate_limited(world: World, attendee: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "search_rate_limit", "2/600")
    codes = [search_as(attendee, world.event, LEFT_PERSON).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# --- Privacy ------------------------------------------------------------------------------


def test_selfie_is_never_persisted(world: World, attendee: TestClient, db: Session, monkeypatch) -> None:
    bucket = get_settings().s3_bucket
    objects_before = storage.get_s3().list_objects_v2(Bucket=bucket).get("KeyCount")
    faces_before = db.scalar(select(func.count()).select_from(Face))

    def no_temp_files(*_a: object, **_k: object) -> None:
        raise AssertionError("selfie handling must not create temporary files")

    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, no_temp_files)
    import starlette.formparsers

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_temp_files)

    # >1 MB per shot would spool to disk with multipart; pad each JPEG past that.
    padded = [(shot, data + b"\x00" * (1024 * 1024 + 1)) for shot, data in selfie_set(LEFT_PERSON)]
    body, headers = selfie_body(padded)
    headers["x-capture-token"] = attendee.post(f"/api/events/{world.event.id}/capture-token").json()["token"]
    r = attendee.post(f"/api/events/{world.event.id}/search?source=camera", content=body, headers=headers)
    assert r.status_code == 200, r.text
    monkeypatch.undo()

    assert storage.get_s3().list_objects_v2(Bucket=bucket).get("KeyCount") == objects_before
    assert db.scalar(select(func.count()).select_from(Face)) == faces_before
    audit_columns = {c["name"] for c in inspect(db.get_bind()).get_columns("search_audit")}
    assert audit_columns == {"id", "user_id", "event_id", "match_count", "created_at"}
    grant_columns = {c["name"] for c in inspect(db.get_bind()).get_columns("search_grants")}
    assert "embedding" not in grant_columns


# --- Download authorization ---------------------------------------------------------------


def test_cannot_download_photos_you_did_not_match(world: World, attendee: TestClient, make_user, login_as, add_member) -> None:
    ev = world.event
    left = str(world.photos["left.jpg"])
    search_as(attendee, ev, LEFT_PERSON)

    other_user = make_user("other@example.com")
    add_member(ev, other_user)
    other = login_as(other_user)
    assert other.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [left]}).status_code == 403
    assert other.get(f"/api/events/{ev.id}/photos/{left}/preview").status_code == 404

    # A matched user can't sneak an unmatched photo into a ZIP either
    mixed = [left, str(world.photos["sky.jpg"])]
    assert attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": mixed}).status_code == 403

    # A download link is bound to the user who requested it
    url = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [left]}).json()["url"]
    assert other.get(url).status_code == 403
    assert TestClient(attendee.app).get(url).status_code == 401  # no session at all


def test_download_link_expires_and_revocation_applies(world: World, attendee: TestClient, db: Session, monkeypatch) -> None:
    ev = world.event
    left = str(world.photos["left.jpg"])
    search_as(attendee, ev, LEFT_PERSON)

    monkeypatch.setattr(get_settings(), "download_token_seconds", -5)
    expired = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [left]}).json()["url"]
    assert attendee.get(expired).status_code == 410
    monkeypatch.undo()

    assert attendee.get("/api/downloads/not-a-token").status_code == 410
    url = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [left]}).json()["url"]
    me = attendee.get("/api/me").json()["id"]
    from app.models import EventMember

    db.get(EventMember, (ev.id, uuid.UUID(me))).status = MemberStatus.revoked
    db.commit()
    assert attendee.get(url).status_code == 403


def test_organizer_can_view_and_download_any_event_photo(world: World, make_user, login_as, add_member) -> None:
    org_user = make_user("org@example.com", UserRole.organizer)
    add_member(world.event, org_user, role=MemberRole.organizer)
    org = login_as(org_user)
    sky = str(world.photos["sky.jpg"])
    assert org.get(f"/api/events/{world.event.id}/photos/{sky}/thumb").status_code == 200
    r = org.post(f"/api/events/{world.event.id}/downloads", json={"photo_ids": [sky]})
    assert r.status_code == 200 and org.get(r.json()["url"]).status_code == 200


def test_download_link_is_bound_to_requesting_user(world: World, attendee: TestClient, make_user, login_as, add_member) -> None:
    """Even a user entitled to the same photo can't redeem someone else's link."""
    ev, left = world.event, str(world.photos["left.jpg"])
    search_as(attendee, ev, LEFT_PERSON)
    twin_user = make_user("twin@example.com")
    add_member(ev, twin_user)
    twin = login_as(twin_user)
    twin.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    search_as(twin, ev, LEFT_PERSON)  # twin matched the same photo

    url = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [left]}).json()["url"]
    r = twin.get(url)
    assert r.status_code == 403 and "another account" in r.json()["detail"]
    assert attendee.get(url).status_code == 200
