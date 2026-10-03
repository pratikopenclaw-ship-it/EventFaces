"""Event logos: organizers upload, members see; re-encoded PNG, bounded, metadata-free."""

import io
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core import storage
from app.models import Event, MemberRole, User, UserRole
from tests.helpers import jpeg_with_gps, solid_jpeg


@pytest.fixture
def org_event(make_user, login_as, make_event, add_member):  # type: ignore[no-untyped-def]
    event = make_event("Logo Party")
    org = make_user("logo-org@example.com", role=UserRole.organizer)
    add_member(event, org, role=MemberRole.organizer)
    return event, login_as(org)


def _png_with_alpha(size: tuple[int, int] = (1200, 600)) -> bytes:
    img = Image.new("RGBA", size, (11, 110, 100, 0))
    img.paste((255, 255, 255, 255), (100, 100, 400, 300))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _put(client: TestClient, event: Event, data: bytes, content_type: str = "image/png"):  # type: ignore[no-untyped-def]
    return client.put(f"/api/events/{event.id}/logo", content=data, headers={"content-type": content_type})


def test_logo_is_reencoded_bounded_and_keeps_transparency(org_event, make_user: Callable[..., User], login_as, add_member, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    r = _put(org, event, _png_with_alpha())
    assert r.status_code == 200 and r.json()["has_logo"] is True
    member = make_user("logo-member@example.com")
    add_member(event, member)
    got = login_as(member).get(f"/api/events/{event.id}/logo")
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(got.content))
    assert img.format == "PNG" and max(img.size) == 512 and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0  # transparency survived
    assert login_as(member).get(f"/api/events/{event.id}").json()["has_logo"] is True


def test_logo_metadata_is_stripped(org_event) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    assert _put(org, event, jpeg_with_gps(solid_jpeg()), "image/jpeg").status_code == 200
    stored = storage.get_bytes(storage.logo_key(event.id))
    img = Image.open(io.BytesIO(stored))
    assert not img.getexif() and not img.info.get("exif") and b"GPS" not in stored


@pytest.mark.parametrize(
    ("data", "status"),
    [(b"not an image at all", 415), (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, 415), (b"x" * (1024 * 1024 + 1), 413)],
    ids=["text", "truncated-png", "too-large"],
)
def test_bad_logos_are_refused(org_event, data: bytes, status: int, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    assert _put(org, event, data).status_code == status
    db.refresh(event)
    assert event.logo_key is None


def test_pixel_bomb_logo_is_refused_before_decoding(org_event) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    img = Image.new("1", (10_000, 10_000))  # 100 MP, a few KB as PNG
    out = io.BytesIO()
    img.save(out, "PNG")
    assert len(out.getvalue()) < 1024 * 1024
    assert _put(org, event, out.getvalue()).status_code == 415


def test_delete_logo_removes_the_object(org_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    _put(org, event, _png_with_alpha())
    key = storage.logo_key(event.id)
    assert storage.head_size(key)
    r = org.delete(f"/api/events/{event.id}/logo")
    assert r.status_code == 200 and r.json()["has_logo"] is False
    assert storage.head_size(key) is None
    assert org.get(f"/api/events/{event.id}/logo").status_code == 404


def test_logo_lives_under_the_event_prefix_so_event_deletion_removes_it() -> None:
    assert storage.logo_key("e1").startswith(storage.event_prefix("e1"))
