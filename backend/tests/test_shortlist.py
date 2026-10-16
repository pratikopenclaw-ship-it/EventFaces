"""An attendee's personal photo shortlist: add/remove, idempotency, authorization,
and that it stays scoped to the user's own event membership and photo access."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PhotoShortlist, UserRole
from app.services import drive
from tests.helpers import FakeDrive, half_photo, search_as

P0 = 0


@pytest.fixture
def world(make_user, login_as, make_event, add_member):  # type: ignore[no-untyped-def]
    event = make_event("Party", drive_folder_id="1ShortlistFolderXXXX")
    admin = login_as(make_user("admin-sl@example.com", UserRole.super_admin))
    drive.set_drive_client(
        FakeDrive({event.drive_folder_id: {"l": ("left.jpg", half_photo("left")), "r": ("right.jpg", half_photo("right"))}})
    )
    admin.post(f"/api/events/{event.id}/sync")
    user = make_user("att-sl@example.com")
    add_member(event, user)
    c = login_as(user)
    from app.services.search import FACE_CONSENT_VERSION

    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    return event, user, c


def test_add_list_and_remove_a_shortlisted_photo(world, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, user, c = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]

    assert c.post(f"/api/events/{event.id}/photos/{photo_id}/shortlist").status_code == 204
    row = db.scalar(select(PhotoShortlist))
    assert (str(row.user_id), str(row.photo_id), str(row.event_id)) == (str(user.id), photo_id, str(event.id))

    listed = c.get(f"/api/events/{event.id}/shortlist").json()
    assert [p["id"] for p in listed] == [photo_id]
    assert c.get(f"/api/events/{event.id}/my-photos").json()[0]["shortlisted"] is True

    assert c.delete(f"/api/events/{event.id}/photos/{photo_id}/shortlist").status_code == 204
    assert c.get(f"/api/events/{event.id}/shortlist").json() == []
    assert db.scalar(select(PhotoShortlist)) is None


def test_adding_twice_is_idempotent(world, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, _, c = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    assert c.post(f"/api/events/{event.id}/photos/{photo_id}/shortlist").status_code == 204
    assert c.post(f"/api/events/{event.id}/photos/{photo_id}/shortlist").status_code == 204
    assert db.scalar(select(PhotoShortlist).order_by(PhotoShortlist.id)) is not None
    assert len(list(db.scalars(select(PhotoShortlist)))) == 1


def test_removing_an_unshortlisted_photo_is_a_no_op(world) -> None:  # type: ignore[no-untyped-def]
    event, _, c = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    assert c.delete(f"/api/events/{event.id}/photos/{photo_id}/shortlist").status_code == 204


def test_cannot_shortlist_a_photo_you_have_no_access_to(world, make_user, login_as, add_member) -> None:  # type: ignore[no-untyped-def]
    event, _, c = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    other = make_user("stranger-sl@example.com")
    add_member(event, other)
    oc = login_as(other)
    assert oc.post(f"/api/events/{event.id}/photos/{photo_id}/shortlist").status_code == 404
    assert oc.post(f"/api/events/{event.id}/photos/{uuid.uuid4()}/shortlist").status_code == 404


def test_shortlist_is_private_to_each_attendee(world, make_user, login_as, add_member) -> None:  # type: ignore[no-untyped-def]
    event, _, c = world
    photo_id = search_as(c, event, P0).json()["matches"][0]["id"]
    c.post(f"/api/events/{event.id}/photos/{photo_id}/shortlist")

    other = make_user("other-sl@example.com")
    add_member(event, other)
    oc = login_as(other)
    assert oc.get(f"/api/events/{event.id}/shortlist").json() == []
