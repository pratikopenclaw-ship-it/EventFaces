"""Organizer-added event video links: URL validation per provider, and that only
organizers may add/remove them while any member can list them."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models import MemberRole, UserRole
from app.services import event_videos


@pytest.fixture
def org_event(make_user, login_as, make_event, add_member):  # type: ignore[no-untyped-def]
    event = make_event("Video Party")
    org = make_user("video-org@example.com", role=UserRole.organizer)
    add_member(event, org, role=MemberRole.organizer)
    return event, login_as(org)


@pytest.mark.parametrize(
    ("url", "provider", "embed_url"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "https://www.youtube.com/embed/dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube", "https://www.youtube.com/embed/dQw4w9WgXcQ"),
        ("https://vimeo.com/76979871", "vimeo", "https://player.vimeo.com/video/76979871"),
        ("https://www.instagram.com/reel/Cabc123XYZ/", "instagram", "https://www.instagram.com/reel/Cabc123XYZ/embed"),
        (
            "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view",
            "drive",
            "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/preview",
        ),
    ],
)
def test_parse_embed_recognizes_each_supported_provider(url: str, provider: str, embed_url: str) -> None:
    embed = event_videos.parse_embed(url)
    assert embed.provider == provider
    assert embed.embed_url == embed_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video.mp4",
        "http://youtu.be/dQw4w9WgXcQ",  # not https
        "https://youtube.com/watch?v=short",  # id too short
        "https://evil.com/youtube.com/watch?v=dQw4w9WgXcQ",
        "not a url at all",
    ],
)
def test_parse_embed_rejects_unsupported_or_malformed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        event_videos.parse_embed(url)


def test_organizer_can_add_list_and_delete_a_video(org_event) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    add = org.post(f"/api/events/{event.id}/videos", json={"title": "Highlights", "url": "https://youtu.be/dQw4w9WgXcQ"})
    assert add.status_code == 201
    body = add.json()
    assert body["provider"] == "youtube"
    assert body["embed_url"] == "https://www.youtube.com/embed/dQw4w9WgXcQ"

    listed = org.get(f"/api/events/{event.id}/videos")
    assert listed.status_code == 200 and len(listed.json()) == 1

    deleted = org.delete(f"/api/events/{event.id}/videos/{body['id']}")
    assert deleted.status_code == 204
    assert org.get(f"/api/events/{event.id}/videos").json() == []


def test_adding_an_unsupported_url_is_422_and_nothing_is_stored(org_event, db: Session) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    resp = org.post(f"/api/events/{event.id}/videos", json={"title": "Nope", "url": "https://example.com/video.mp4"})
    assert resp.status_code == 422
    assert event_videos.list_videos(db, event) == []


def test_attendee_can_list_but_not_add_or_delete(make_user, login_as, add_member, org_event) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    attendee = make_user("video-attendee@example.com")
    add_member(event, attendee)
    client = login_as(attendee)

    assert client.get(f"/api/events/{event.id}/videos").status_code == 200
    assert client.post(f"/api/events/{event.id}/videos", json={"title": "x", "url": "https://youtu.be/dQw4w9WgXcQ"}).status_code == 403
    assert client.delete(f"/api/events/{event.id}/videos/{uuid.uuid4()}").status_code == 403


def test_deleting_an_unknown_video_is_404(org_event) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    assert org.delete(f"/api/events/{event.id}/videos/{uuid.uuid4()}").status_code == 404


def test_video_from_another_event_cannot_be_deleted_via_this_event(org_event, make_event) -> None:  # type: ignore[no-untyped-def]
    event, org = org_event
    other = make_event("Other Event")
    add = org.post(f"/api/events/{event.id}/videos", json={"title": "x", "url": "https://youtu.be/dQw4w9WgXcQ"})
    video_id = add.json()["id"]
    assert org.delete(f"/api/events/{other.id}/videos/{video_id}").status_code in (403, 404)
