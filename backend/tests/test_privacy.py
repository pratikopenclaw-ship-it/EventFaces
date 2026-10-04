"""Delete-my-data, removal requests from people in photos, and the search audit log."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import storage
from app.models import (
    EventMember,
    Face,
    MemberRole,
    ModerationMode,
    Photo,
    PhotoStatus,
    RemovalRequest,
    SearchAudit,
    SearchGrant,
    User,
    UserRole,
)
from app.services import drive
from app.services.search import FACE_CONSENT_VERSION
from tests.conftest import PASSWORD, FakeMailer, new_client
from tests.helpers import FakeDrive, half_photo, search_as, selfie_of, solid_jpeg


def _delete_me(c: TestClient, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return c.request("DELETE", "/api/me", json={"password": password})


# --- Delete my data -------------------------------------------------------------------------


def test_delete_my_data_erases_everything_personal(make_user, login_as, make_event, add_member, db: Session, mailer: FakeMailer) -> None:
    event = make_event("Party", guest_upload_enabled=True, moderation_mode=ModerationMode.auto, drive_folder_id="1PartyFolderXXXXXXX")
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    drive.set_drive_client(FakeDrive({event.drive_folder_id: {"g": ("g.jpg", half_photo("left"))}}))
    admin.post(f"/api/events/{event.id}/sync")

    user = make_user("leaving@example.com")
    user_id = user.id
    add_member(event, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    search_as(c, event, 0)
    data = half_photo("right")
    start = c.post(f"/api/events/{event.id}/uploads", json={"filename": "mine.jpg", "content_type": "image/jpeg", "size": len(data)}).json()
    httpx.put(start["upload_url"], content=data, headers={"content-type": "image/jpeg"})
    c.post(f"/api/events/{event.id}/uploads/{start['photo_id']}/complete")
    upload_id = uuid.UUID(start["photo_id"])
    upload = db.get(Photo, upload_id)
    upload_keys = [upload.original_key, upload.thumb_key]
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == upload_id)) == 3

    assert _delete_me(c, "wrong-password-123").status_code == 403
    r = _delete_me(c)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"]["uploads"] == 1 and r.json()["deleted"]["matches"] == 1

    db.expire_all()
    assert db.get(User, user_id) is None
    assert db.get(EventMember, (event.id, user_id)) is None
    assert db.scalar(select(func.count()).select_from(SearchGrant).where(SearchGrant.user_id == user_id)) == 0
    assert db.get(Photo, upload_id) is None
    assert all(storage.head_size(k) is None for k in upload_keys)
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == upload_id)) == 0
    # Audit row survives without the person
    assert db.scalars(select(SearchAudit.user_id)).all() == [None]
    # The organizer's Drive photo is untouched
    assert db.scalar(select(func.count()).select_from(Photo).where(Photo.source == "drive")) == 1
    # Session is gone and login fails
    assert c.get("/api/me").status_code == 401
    assert new_client().post("/api/auth/login", json={"email": "leaving@example.com", "password": PASSWORD}).status_code == 401
    assert mailer.outbox[-1].subject == "Your EventFaces data was deleted"


def test_last_super_admin_cannot_delete_themselves(make_user, login_as) -> None:
    only = login_as(make_user("only-admin@example.com", UserRole.super_admin))
    assert _delete_me(only).status_code == 409
    make_user("second-admin@example.com", UserRole.super_admin)
    assert _delete_me(only).status_code == 200


# --- Removal requests ---------------------------------------------------------------------------


@pytest.fixture
def two_events(make_user, login_as, make_event, add_member):
    """Event A with left+right halves and a sky photo; event B with the same left half."""
    admin = login_as(make_user("admin@example.com", UserRole.super_admin))
    a = make_event("Conference", drive_folder_id="1ConferenceFolderXXX")
    b = make_event("Other", drive_folder_id="1OtherFolderXXXXXXXX")
    drive.set_drive_client(
        FakeDrive(
            {
                a.drive_folder_id: {"l": ("left.jpg", half_photo("left")), "r": ("right.jpg", half_photo("right")), "s": ("sky.jpg", solid_jpeg())},
                b.drive_folder_id: {"l2": ("left.jpg", half_photo("left"))},
            }
        )
    )
    admin.post(f"/api/events/{a.id}/sync")
    admin.post(f"/api/events/{b.id}/sync")
    org_user = make_user("org@example.com", UserRole.organizer)
    add_member(a, org_user, role=MemberRole.organizer)
    return a, b, login_as(org_user)


def _start_removal(mailer: FakeMailer, slug: str, email: str = "bystander@example.com") -> str:
    c = new_client()
    assert c.get(f"/api/removal-requests/event/{slug}").json()["event_name"]
    r = c.post("/api/removal-requests", json={"event": slug, "email": email, "message": "I didn't agree to be photographed"})
    assert r.status_code == 202
    mail = next(m for m in reversed(mailer.outbox) if m.to == email)
    return mail.body.split("/removal/")[1].split()[0]


def test_removal_request_end_to_end(two_events, db: Session, mailer: FakeMailer) -> None:
    a, b, org = two_events
    token = _start_removal(mailer, a.slug)
    c = new_client()  # not a user at all
    assert c.get(f"/api/removal-requests/{token}").json() == {"event_name": "Conference", "email": "bystander@example.com"}

    r = c.post(f"/api/removal-requests/{token}/submit", content=selfie_of(0), headers={"content-type": "image/jpeg"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted"] is True and "matched" not in str(body)  # requester never sees matches
    assert c.post(f"/api/removal-requests/{token}/submit").status_code == 410  # single use
    assert any(m.to == "org@example.com" and "removal request" in m.subject for m in mailer.outbox)

    # Organizer sees exactly the matching photo of THIS event (not event B's identical copy)
    left_a = db.scalar(select(Photo.id).where(Photo.event_id == a.id, Photo.original_filename == "left.jpg"))
    reqs = org.get(f"/api/events/{a.id}/removal-requests").json()
    assert len(reqs) == 1 and reqs[0]["matched_photo_ids"] == [str(left_a)]
    assert reqs[0]["message"] == "I didn't agree to be photographed"

    r = org.post(f"/api/events/{a.id}/removal-requests/{reqs[0]['id']}/resolve", json={"action": "remove"})
    assert r.json() == {"removed": 1}
    db.expire_all()
    assert db.get(Photo, left_a).status == PhotoStatus.removed
    assert db.scalar(select(func.count()).select_from(Face).where(Face.photo_id == left_a)) == 0
    assert db.scalar(select(Photo.status).where(Photo.event_id == b.id)) == PhotoStatus.published
    assert "removed 1 photo" in next(m for m in reversed(mailer.outbox) if m.to == "bystander@example.com").body
    assert org.get(f"/api/events/{a.id}/removal-requests").json() == []


def test_removal_request_without_selfie_and_decline(two_events, mailer: FakeMailer) -> None:
    a, _, org = two_events
    token = _start_removal(mailer, a.slug)
    assert new_client().post(f"/api/removal-requests/{token}/submit").status_code == 200
    req = org.get(f"/api/events/{a.id}/removal-requests").json()[0]
    assert req["matched_photo_ids"] == []
    assert org.post(f"/api/events/{a.id}/removal-requests/{req['id']}/resolve", json={"action": "decline"}).json() == {"removed": 0}
    assert "did not remove" in next(m for m in reversed(mailer.outbox) if m.to == "bystander@example.com").body


def test_removal_request_unknown_event_is_indistinguishable(mailer: FakeMailer) -> None:
    r = new_client().post("/api/removal-requests", json={"event": "no-such-event", "email": "x@example.com"})
    assert r.status_code == 202 and mailer.outbox == []


def test_removal_request_is_scoped_to_organizers_of_that_event(two_events, make_user, login_as, add_member, mailer: FakeMailer) -> None:
    a, b, _ = two_events
    other_org = make_user("other-org@example.com", UserRole.organizer)
    add_member(b, other_org, role=MemberRole.organizer)
    token = _start_removal(mailer, a.slug)
    new_client().post(f"/api/removal-requests/{token}/submit")
    c = login_as(other_org)
    assert c.get(f"/api/events/{a.id}/removal-requests").status_code == 403
    assert c.get(f"/api/events/{b.id}/removal-requests").json() == []


def test_removal_request_rate_limited(two_events, mailer: FakeMailer) -> None:
    a, _, _ = two_events
    c = new_client()
    codes = [
        c.post("/api/removal-requests", json={"event": a.slug, "email": f"p{i}@example.com"}).status_code for i in range(6)
    ]
    assert codes == [202] * 5 + [429]


def test_removal_request_token_rejected_after_expiry(two_events, db: Session, mailer: FakeMailer) -> None:
    from datetime import timedelta

    a, _, _ = two_events
    token = _start_removal(mailer, a.slug)
    req = db.scalar(select(RemovalRequest))
    req.created_at = req.created_at - timedelta(hours=49)
    db.commit()
    assert new_client().post(f"/api/removal-requests/{token}/submit").status_code == 410


# --- Search audit log ---------------------------------------------------------------------------


def test_search_log_visible_to_organizers_only(two_events, make_user, login_as, add_member) -> None:
    a, _, org = two_events
    user = make_user("att@example.com")
    add_member(a, user)
    c = login_as(user)
    c.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    search_as(c, a, 0)
    log = org.get(f"/api/events/{a.id}/search-log").json()
    assert [(row["user_email"], row["match_count"]) for row in log] == [("att@example.com", 1)]
    assert c.get(f"/api/events/{a.id}/search-log").status_code == 403


# --- Rate limits on every sensitive endpoint ------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body", "limit"),
    [
        ("/api/auth/signup", {"accept_terms": True, "email": "s{i}@example.com", "password": PASSWORD}, 10),
        ("/api/auth/forgot-password", {"email": "f{i}@example.com"}, 5),
        ("/api/auth/resend-verification", {"email": "r{i}@example.com"}, 5),
    ],
)
def test_public_auth_endpoints_rate_limited(path: str, body: dict, limit: int, mailer: FakeMailer) -> None:
    c = new_client()
    codes = []
    for i in range(limit + 1):
        payload = {k: v.format(i=i) if isinstance(v, str) else v for k, v in body.items()}
        codes.append(c.post(path, json=payload).status_code)
    assert codes[-1] == 429 and 429 not in codes[:-1]


def test_upload_start_rate_limited(make_user, login_as, make_event, add_member, monkeypatch) -> None:
    from app.core.config import get_settings

    event = make_event("U", guest_upload_enabled=True)
    user = make_user("u@example.com")
    add_member(event, user)
    c = login_as(user)
    monkeypatch.setattr(get_settings(), "guest_upload_rate_limit", "2/3600")
    body = {"filename": "a.jpg", "content_type": "image/jpeg", "size": 100}
    assert [c.post(f"/api/events/{event.id}/uploads", json=body).status_code for _ in range(3)] == [201, 201, 429]
