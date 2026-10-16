"""Photo watermarking: an organizer's event logo is composited onto served photos
(thumb, preview, download/ZIP) only when the event has a logo, and only at serve time
-- the stored original (used for face detection) is never touched."""

import io
import uuid
from zipfile import ZipFile

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.core import storage
from app.models import Event, IndexStatus, MemberRole, Photo, PhotoSource, PhotoStatus, UserRole
from app.services import watermark
from tests.helpers import solid_jpeg


def _logo_png(size: tuple[int, int] = (200, 100)) -> bytes:
    img = Image.new("RGBA", size, (255, 0, 0, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_apply_pastes_the_logo_without_changing_photo_size() -> None:
    photo_bytes = solid_jpeg(size=(320, 240))
    out = watermark.apply(photo_bytes, _logo_png(), quality=85)
    before, after = Image.open(io.BytesIO(photo_bytes)), Image.open(io.BytesIO(out))
    assert after.size == before.size
    assert out != photo_bytes
    # A point well inside the pasted (opaque red) logo's bottom-right box.
    target_w = round(min(before.size) * watermark.LOGO_WIDTH_FRACTION)
    margin = round(min(before.size) * watermark.MARGIN_FRACTION)
    x = before.width - margin - target_w // 2
    y = before.height - margin - target_w // 4
    r, g, b = after.getpixel((x, y))  # JPEG re-encoding introduces minor lossy drift
    assert r > 200 and g < 50 and b < 50
    # Top-left is untouched.
    assert after.getpixel((0, 0)) == before.convert("RGB").getpixel((0, 0))


def test_maybe_apply_is_a_noop_without_a_logo(db: Session) -> None:
    event = Event(slug="no-logo", name="No Logo", access_code="X", created_by=None)
    photo_bytes = solid_jpeg()
    assert watermark.maybe_apply(photo_bytes, event, None, quality=85) == photo_bytes


@pytest.fixture
def branded_event(make_user, login_as, make_event, add_member, db: Session):  # type: ignore[no-untyped-def]
    event = make_event("Branded Gala")
    org = make_user("wm-org@example.com", role=UserRole.organizer)
    add_member(event, org, role=MemberRole.organizer)
    org_client = login_as(org)
    r = org_client.put(f"/api/events/{event.id}/logo", content=_logo_png(), headers={"content-type": "image/png"})
    assert r.status_code == 200 and r.json()["has_logo"] is True

    attendee = make_user("wm-attendee@example.com")
    add_member(event, attendee)

    photo = Photo(
        id=uuid.uuid4(),
        event_id=event.id,
        source=PhotoSource.drive,
        drive_file_id="wm-1",
        original_filename="p.jpg",
        status=PhotoStatus.published,
        index_status=IndexStatus.indexed,
        uploaded_by=attendee.id,  # own upload: viewable without a search grant
    )
    raw = solid_jpeg()
    for variant in ("original", "preview", "thumb"):
        key = storage.photo_key(event.id, photo.id, variant)
        storage.put_jpeg(key, raw)
        setattr(photo, f"{variant}_key", key)
    db.add(photo)
    db.commit()

    return event, photo, raw, login_as(attendee)


def test_thumb_and_preview_are_watermarked_when_the_event_has_a_logo(branded_event) -> None:  # type: ignore[no-untyped-def]
    event, photo, raw, attendee = branded_event
    for variant in ("thumb", "preview"):
        r = attendee.get(f"/api/events/{event.id}/photos/{photo.id}/{variant}")
        assert r.status_code == 200
        assert r.content != raw


def test_download_and_zip_are_watermarked_when_the_event_has_a_logo(branded_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, photo, raw, attendee = branded_event

    single = attendee.post(f"/api/events/{event.id}/downloads", json={"photo_ids": [str(photo.id)]})
    assert single.status_code == 200
    got = attendee.get(single.json()["url"])
    assert got.status_code == 200 and got.content != raw

    photo2 = Photo(
        id=uuid.uuid4(),
        event_id=event.id,
        source=PhotoSource.drive,
        drive_file_id="wm-2",
        original_filename="p2.jpg",
        status=PhotoStatus.published,
        index_status=IndexStatus.indexed,
        uploaded_by=photo.uploaded_by,
    )
    for variant in ("original", "preview", "thumb"):
        key = storage.photo_key(event.id, photo2.id, variant)
        storage.put_jpeg(key, raw)
        setattr(photo2, f"{variant}_key", key)
    db.add(photo2)
    db.commit()

    zipped = attendee.post(
        f"/api/events/{event.id}/downloads", json={"photo_ids": [str(photo.id), str(photo2.id)]}
    )
    assert zipped.status_code == 200
    got_zip = attendee.get(zipped.json()["url"])
    assert got_zip.status_code == 200
    with ZipFile(io.BytesIO(got_zip.content)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        for name in names:
            assert zf.read(name) != raw


def test_photos_are_not_watermarked_without_a_logo(make_user, login_as, make_event, add_member, db: Session) -> None:  # type: ignore[no-untyped-def]
    event = make_event("Plain Gala")
    attendee = make_user("plain-attendee@example.com")
    add_member(event, attendee)
    photo = Photo(
        id=uuid.uuid4(),
        event_id=event.id,
        source=PhotoSource.drive,
        drive_file_id="plain-1",
        original_filename="p.jpg",
        status=PhotoStatus.published,
        index_status=IndexStatus.indexed,
        uploaded_by=attendee.id,
    )
    raw = solid_jpeg()
    for variant in ("original", "preview", "thumb"):
        key = storage.photo_key(event.id, photo.id, variant)
        storage.put_jpeg(key, raw)
        setattr(photo, f"{variant}_key", key)
    db.add(photo)
    db.commit()

    client = login_as(attendee)
    for variant in ("thumb", "preview"):
        r = client.get(f"/api/events/{event.id}/photos/{photo.id}/{variant}")
        assert r.status_code == 200 and r.content == raw
