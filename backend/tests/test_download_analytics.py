"""photos.download_count: a plain aggregate incremented on redemption, used only to let
organizers sort the admin photo listing by engagement (never tied to who downloaded)."""

from sqlalchemy.orm import Session

from app.models import Photo
from tests.helpers import search_as
from tests.test_search import LEFT_PERSON, RIGHT_PERSON, World, attendee, world  # noqa: F401 (fixture re-export)


def test_single_download_increments_the_count(world: World, attendee, db: Session) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    ev, photos = world.event, world.photos
    assert search_as(attendee, ev, LEFT_PERSON).status_code == 200
    photo_id = photos["left.jpg"]

    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [str(photo_id)]})
    attendee.get(r.json()["url"])
    db.expire_all()
    assert db.get(Photo, photo_id).download_count == 1

    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [str(photo_id)]})
    attendee.get(r.json()["url"])
    db.expire_all()
    assert db.get(Photo, photo_id).download_count == 2


def test_zip_download_increments_every_photo_in_it(world: World, attendee, db: Session) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    ev, photos = world.event, world.photos
    assert search_as(attendee, ev, LEFT_PERSON).status_code == 200
    assert search_as(attendee, ev, RIGHT_PERSON).status_code == 200
    ids = [str(photos["left.jpg"]), str(photos["right.jpg"])]

    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": ids})
    attendee.get(r.json()["url"])
    db.expire_all()
    assert db.get(Photo, photos["left.jpg"]).download_count == 1
    assert db.get(Photo, photos["right.jpg"]).download_count == 1
    assert db.get(Photo, photos["sky.jpg"]).download_count == 0


def test_organizer_can_sort_photos_by_downloads(world: World, attendee, db: Session) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    ev, photos = world.event, world.photos
    assert search_as(attendee, ev, LEFT_PERSON).status_code == 200
    assert search_as(attendee, ev, RIGHT_PERSON).status_code == 200

    # left.jpg gets downloaded twice, right.jpg once, sky.jpg never.
    for _ in range(2):
        r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [str(photos["left.jpg"])]})
        attendee.get(r.json()["url"])
    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [str(photos["right.jpg"])]})
    attendee.get(r.json()["url"])

    items = world.admin.get(f"/api/events/{ev.id}/photos?sort=downloads").json()["items"]
    ranked = [p["id"] for p in items]
    assert ranked.index(str(photos["left.jpg"])) < ranked.index(str(photos["right.jpg"]))
    assert ranked.index(str(photos["right.jpg"])) < ranked.index(str(photos["sky.jpg"]))
    counts = {p["id"]: p["download_count"] for p in items}
    assert counts[str(photos["left.jpg"])] == 2
    assert counts[str(photos["right.jpg"])] == 1
    assert counts[str(photos["sky.jpg"])] == 0


def test_default_sort_is_unaffected_by_downloads(world: World, attendee, db: Session) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    ev, photos = world.event, world.photos
    assert search_as(attendee, ev, LEFT_PERSON).status_code == 200
    r = attendee.post(f"/api/events/{ev.id}/downloads", json={"photo_ids": [str(photos["left.jpg"])]})
    attendee.get(r.json()["url"])

    created_at_order = [p["id"] for p in world.admin.get(f"/api/events/{ev.id}/photos").json()["items"]]
    newest_first = [p["id"] for p in world.admin.get(f"/api/events/{ev.id}/photos?sort=created_at").json()["items"]]
    assert created_at_order == newest_first
