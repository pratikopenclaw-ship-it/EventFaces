"""New-photo alerts (Part 1): tell attendees who searched an event that new photos went live.
Nothing biometric is stored (docs/superpowers/specs/2026-10-20-new-photo-alerts-design.md)."""

import json
import re
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.db import SessionLocal, engine
from app.core.security import utcnow
from app.main import app
from app.models import AlertToken, EventPhotoAlert, LegalAcceptance, MemberStatus, User, EventMember, IndexStatus, MemberRole, ModerationMode, Photo, PhotoSource, PhotoStatus, UserRole
from app.services import photo_alerts, photo_pipeline, push, tokens
from app.services.search import FACE_CONSENT_VERSION
from tests.conftest import FakeMailer
from tests.helpers import group_photo_bytes, search_as, solid_jpeg
from tests.test_push import FakeAPNs, _device, apns  # noqa: F401 - the APNs fixture

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def w(db: Session, make_user, login_as, make_event, add_member) -> SimpleNamespace:
    event = make_event("Summer Party", guest_upload_enabled=True, moderation_mode=ModerationMode.manual)
    org_user = make_user("org@example.com", UserRole.organizer)
    attendee_user = make_user("guest@example.com")
    add_member(event, org_user, role=MemberRole.organizer)
    add_member(event, attendee_user)

    def photo(status: PhotoStatus = PhotoStatus.processing, image: bytes | None = None, faces: int = 0) -> Photo:
        p = Photo(
            id=uuid.uuid4(),
            event_id=event.id,
            source=PhotoSource.drive,
            drive_file_id=uuid.uuid4().hex,
            original_filename="party.jpg",
            status=status,
            index_status=IndexStatus.queued,
            face_count=faces,
        )
        for variant in ("original", "preview", "thumb"):
            key = storage.photo_key(event.id, p.id, variant)
            storage.put_jpeg(key, image or solid_jpeg())
            setattr(p, f"{variant}_key", key)
        db.add(p)
        db.commit()
        return p

    attendee = login_as(attendee_user)
    attendee.post("/api/me/face-consent", json={"version": FACE_CONSENT_VERSION})
    return SimpleNamespace(event=event, org=login_as(org_user), attendee=attendee, attendee_user=attendee_user, photo=photo)


def _search(w: SimpleNamespace) -> None:
    r = search_as(w.attendee, w.event)
    assert r.status_code == 200, r.text


def _row(db: Session, w: SimpleNamespace) -> EventPhotoAlert | None:
    db.expire_all()
    return db.get(EventPhotoAlert, (w.attendee_user.id, w.event.id))


def _banner(w: SimpleNamespace) -> bool:
    r = w.attendee.get(f"/api/events/{w.event.id}")
    assert r.status_code == 200, r.text
    return r.json()["new_photos_since_last_search"]


# --- Task 1: published_at -------------------------------------------------------------


def test_index_publishes_with_published_at(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(image=group_photo_bytes())
    assert photo_pipeline.index_photo(db, p.id) == 6
    db.expire_all()
    photo = db.get(Photo, p.id)
    assert photo.status == PhotoStatus.published
    assert photo.published_at is not None and abs(utcnow() - photo.published_at) < timedelta(seconds=5)


def test_moderation_approval_sets_published_at(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(status=PhotoStatus.pending_review)
    r = w.org.post(f"/api/events/{w.event.id}/photos/{p.id}/moderate", json={"action": "approve"})
    assert r.status_code == 204, r.text
    db.expire_all()
    photo = db.get(Photo, p.id)
    assert photo.status == PhotoStatus.published and photo.published_at is not None


def test_reindex_keeps_published_at(w: SimpleNamespace, db: Session) -> None:
    p = w.photo(image=group_photo_bytes())
    photo_pipeline.index_photo(db, p.id)
    db.expire_all()
    first = db.get(Photo, p.id).published_at
    photo_pipeline.index_photo(db, p.id)  # e.g. reindex-faces after a model change
    db.expire_all()
    assert db.get(Photo, p.id).published_at == first


def test_only_publish_helper_sets_published() -> None:
    """Every transition to published goes through photo_pipeline.publish, so published_at
    (what alerts batch on) can't be missed by a future path."""
    pattern = re.compile(r"\.status\s*=\s*PhotoStatus\.published\b|status=PhotoStatus\.published\b")
    hits = [
        (path.relative_to(APP).as_posix(), n)
        for path in APP.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert len(hits) == 1 and hits[0][0] == "services/photo_pipeline.py", hits
    source = (APP / "services/photo_pipeline.py").read_text().splitlines()
    body = source[source.index("def publish(photo: Photo) -> None:") :][:6]
    assert any(pattern.search(line) for line in body)


# --- Task 2: subscribe on search, toggles, banner flag ----------------------------------


def test_search_records_subscription(w: SimpleNamespace, db: Session) -> None:
    assert _row(db, w) is None
    _search(w)
    row = _row(db, w)
    assert row is not None and row.enabled and abs(utcnow() - row.last_searched_at) < timedelta(seconds=30)
    first = row.last_searched_at
    assert w.attendee.put(f"/api/events/{w.event.id}/photo-alerts", json={"enabled": False}).status_code == 200
    _search(w)
    row = _row(db, w)
    assert row.last_searched_at > first and row.enabled is False  # a new search keeps the opt-out


def test_banner_flag(w: SimpleNamespace, db: Session) -> None:
    assert _banner(w) is False  # never searched
    _search(w)
    assert _banner(w) is False
    w.photo(image=solid_jpeg())  # faceless photos never count
    photo_pipeline.index_photo(db, w.photo(image=solid_jpeg()).id)
    assert _banner(w) is False
    photo_pipeline.index_photo(db, w.photo(image=group_photo_bytes()).id)
    assert _banner(w) is True
    _search(w)
    assert _banner(w) is False


def test_toggle_requires_prior_search(w: SimpleNamespace) -> None:
    url = f"/api/events/{w.event.id}/photo-alerts"
    assert w.attendee.get(url).json() == {"subscribed": False, "enabled": False}
    r = w.attendee.put(url, json={"enabled": False})
    assert r.status_code == 409 and r.json()["detail"] == "search_first"


def test_toggle_roundtrip(w: SimpleNamespace) -> None:
    url = f"/api/events/{w.event.id}/photo-alerts"
    _search(w)
    assert w.attendee.get(url).json() == {"subscribed": True, "enabled": True}
    assert w.attendee.put(url, json={"enabled": False}).json() == {"subscribed": True, "enabled": False}
    assert w.attendee.get(url).json() == {"subscribed": True, "enabled": False}
    assert w.attendee.put(url, json={"enabled": True}).json() == {"subscribed": True, "enabled": True}


def test_preferences_new_photo_alerts(w: SimpleNamespace, db: Session) -> None:
    assert w.attendee.get("/api/me").json()["new_photo_alerts"] is True
    r = w.attendee.patch("/api/me/preferences", json={"new_photo_alerts": False})
    assert r.status_code == 200 and r.json()["new_photo_alerts"] is False
    assert not [h for h in r.headers.get_list("set-cookie") if h.startswith("ef_theme=")]  # theme untouched
    assert r.json()["theme"] == "system"
    r = w.attendee.patch("/api/me/preferences", json={"theme": "dark"})
    assert r.json()["theme"] == "dark" and r.json()["new_photo_alerts"] is False


def test_admin_event_out_has_no_alert_rows(w: SimpleNamespace) -> None:
    """Organizers never see who searched (Privacy Notice): no alert data in admin views."""
    _search(w)
    admin = w.org.get(f"/api/events/{w.event.id}/admin").json()
    members = w.org.get(f"/api/events/{w.event.id}/members").json()
    text = str(admin) + str(members)
    for field in ("last_searched_at", "new_photos_since_last_search", "notified_through", "last_notified_at", "subscribed"):
        assert field not in text


def test_organizer_can_disable_notify_new_photos(w: SimpleNamespace) -> None:
    assert w.org.get(f"/api/events/{w.event.id}/admin").json()["notify_new_photos"] is True
    r = w.org.patch(f"/api/events/{w.event.id}", json={"notify_new_photos": False})
    assert r.status_code == 200 and r.json()["notify_new_photos"] is False


# --- Task 3: unsubscribe tokens ---------------------------------------------------------

UNSUB = "/api/alerts/unsubscribe"


def _anonymous() -> TestClient:
    """A mail client or link opened without a session: no cookies, no CSRF header."""
    return TestClient(app)


def _token(db: Session, w: SimpleNamespace, expires_in: timedelta = timedelta(days=30)) -> str:
    raw = tokens.issue_alert_token(db, w.attendee_user.id, w.event.id, utcnow() + expires_in)
    db.commit()
    return raw


def _enabled(db: Session, w: SimpleNamespace) -> tuple[bool, bool]:
    """(this event's alerts on, account-wide alerts on)"""
    row = _row(db, w)
    return row.enabled, db.get(User, w.attendee_user.id).new_photo_alerts


def test_unsubscribe_event_scope(w: SimpleNamespace, db: Session) -> None:
    _search(w)
    r = _anonymous().post(UNSUB, json={"token": _token(db, w), "scope": "event"})
    assert r.status_code == 200 and r.json() == {"detail": "ok"}
    assert _enabled(db, w) == (False, True)


def test_unsubscribe_all_scope(w: SimpleNamespace, db: Session) -> None:
    _search(w)
    token = _token(db, w)
    assert _anonymous().post(UNSUB, json={"token": token, "scope": "event"}).status_code == 200
    assert _anonymous().post(UNSUB, json={"token": token, "scope": "all"}).status_code == 200  # reusable
    assert _enabled(db, w) == (False, False)


def test_one_click_form_post(w: SimpleNamespace, db: Session) -> None:
    """RFC 8058: the mail provider POSTs List-Unsubscribe=One-Click to the header's URL."""
    _search(w)
    r = _anonymous().post(
        f"{UNSUB}?token={_token(db, w)}",
        content=b"List-Unsubscribe=One-Click",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    assert _enabled(db, w) == (False, True)


@pytest.mark.parametrize("kind", ["unknown", "expired", "other-event"])
def test_bad_or_expired_token_looks_ok_and_changes_nothing(w: SimpleNamespace, db: Session, make_event, kind: str) -> None:
    _search(w)
    if kind == "unknown":
        token = "not-a-real-token-123"
    elif kind == "expired":
        token = _token(db, w, expires_in=timedelta(seconds=-1))
    else:
        other = make_event("Other")
        token = tokens.issue_alert_token(db, w.attendee_user.id, other.id, utcnow() + timedelta(days=1))
        db.commit()
    r = _anonymous().post(UNSUB, json={"token": token, "scope": "event" if kind != "expired" else "all"})
    assert r.status_code == 200 and r.json() == {"detail": "ok"}  # no oracle about tokens or accounts
    assert _enabled(db, w) == (True, True)


def test_token_hashed_at_rest(w: SimpleNamespace, db: Session) -> None:
    raw = _token(db, w)
    stored = db.scalars(select(AlertToken.token_hash)).all()
    assert raw not in stored and len(stored) == 1 and len(stored[0]) == 64


def test_unsubscribe_get_has_no_effect(w: SimpleNamespace, db: Session) -> None:
    """Link scanners prefetch URLs: a GET must never unsubscribe."""
    _search(w)
    assert _anonymous().get(f"{UNSUB}?token={_token(db, w)}").status_code == 405
    assert _enabled(db, w) == (True, True)


def test_unsubscribe_without_cookie_skips_csrf(w: SimpleNamespace, db: Session) -> None:
    _search(w)
    assert _anonymous().post(UNSUB, json={"token": _token(db, w), "scope": "event"}).status_code == 200


def test_unsubscribe_with_cookie_needs_csrf(w: SimpleNamespace, db: Session) -> None:
    _search(w)
    token = _token(db, w)
    csrf = w.attendee.headers.pop("X-CSRF-Token", None)
    assert w.attendee.post(UNSUB, json={"token": token, "scope": "event"}).status_code == 403
    assert _enabled(db, w) == (True, True)
    w.attendee.headers["X-CSRF-Token"] = csrf
    assert w.attendee.post(UNSUB, json={"token": token, "scope": "event"}).status_code == 200


def test_unsubscribe_is_rate_limited_per_ip(w: SimpleNamespace) -> None:
    c = _anonymous()
    codes = [c.post(UNSUB, json={"token": f"guess-{i}", "scope": "event"}).status_code for i in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


# --- Task 4: the sender (beat task, push, email) ---------------------------------------
# Times are relative to B, two hours ago: the search is moved there, photos go live after
# it, and run() gets an explicit `now`.

M = timedelta(minutes=1)


@pytest.fixture
def b(w: SimpleNamespace, db: Session) -> SimpleNamespace:
    """w after a search, with the search moved to B."""
    _search(w)
    base = utcnow() - timedelta(hours=2)
    db.get(EventPhotoAlert, (w.attendee_user.id, w.event.id)).last_searched_at = base
    db.commit()

    def live(at: timedelta, faces: int = 1) -> Photo:
        p = w.photo(status=PhotoStatus.published, faces=faces)
        p.published_at = base + at
        db.commit()
        return p

    w.base, w.live = base, live
    return w


def _run(db: Session, b: SimpleNamespace, at: timedelta) -> int:
    db.expire_all()  # the beat task runs in a fresh session; API calls changed rows since
    return photo_alerts.run(db, b.base + at)


def _alerts(mailer: FakeMailer, b: SimpleNamespace) -> list:  # type: ignore[type-arg]
    return [m for m in mailer.outbox if m.to == b.attendee_user.email]


def test_burst_sends_one_alert_after_quiet_window(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(1 * M)
    b.live(3 * M)
    assert _run(db, b, 12 * M) == 0  # newest is 9 min old: the burst may continue
    assert _run(db, b, 14 * M) == 1
    assert len(_alerts(mailer, b)) == 1
    assert _run(db, b, 30 * M) == 0  # covered


def test_no_alert_while_burst_continues(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(1 * M)
    b.live(8 * M)
    assert _run(db, b, 12 * M) == 0  # 11 min after the first photo, 4 after the newest
    assert _run(db, b, 19 * M) == 1


def test_faceless_photos_never_alert(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(1 * M, faces=0)
    assert _run(db, b, 30 * M) == 0 and _alerts(mailer, b) == []


def test_photos_before_last_search_never_alert(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(-5 * M)
    assert _run(db, b, 30 * M) == 0


def test_search_after_publish_suppresses_alert(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(1 * M)
    _search(b)  # searched again (now) after the photo went live: they've seen it
    db.expire_all()
    assert photo_alerts.run(db, utcnow() + 15 * M) == 0


def test_moderated_photo_alerts(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    p = b.photo(status=PhotoStatus.pending_review, faces=2)
    assert b.org.post(f"/api/events/{b.event.id}/photos/{p.id}/moderate", json={"action": "approve"}).status_code == 204
    db.expire_all()
    assert photo_alerts.run(db, utcnow() + 11 * M) == 1


def test_24h_cap_then_catch_up(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(1 * M)
    assert _run(db, b, 15 * M) == 1
    b.live(60 * M)
    assert _run(db, b, 80 * M) == 0  # a second notice within 24 h is held back
    assert _run(db, b, 15 * M + timedelta(hours=24, minutes=1)) == 1  # nothing lost
    assert len(_alerts(mailer, b)) == 2


def test_event_toggle_off(b: SimpleNamespace, db: Session) -> None:
    assert b.attendee.put(f"/api/events/{b.event.id}/photo-alerts", json={"enabled": False}).status_code == 200
    b.live(1 * M)
    assert _run(db, b, 30 * M) == 0


def test_account_toggle_off(b: SimpleNamespace, db: Session) -> None:
    assert b.attendee.patch("/api/me/preferences", json={"new_photo_alerts": False}).status_code == 200
    b.live(1 * M)
    assert _run(db, b, 30 * M) == 0


def test_organizer_toggle_off(b: SimpleNamespace, db: Session) -> None:
    assert b.org.patch(f"/api/events/{b.event.id}", json={"notify_new_photos": False}).status_code == 200
    b.live(1 * M)
    assert _run(db, b, 30 * M) == 0


def test_revoked_member_not_alerted(b: SimpleNamespace, db: Session) -> None:
    m = db.scalar(select(EventMember).where(EventMember.event_id == b.event.id, EventMember.user_id == b.attendee_user.id))
    m.status = MemberStatus.revoked
    db.commit()
    b.live(1 * M)
    assert _run(db, b, 30 * M) == 0


def test_expired_access_not_alerted(b: SimpleNamespace, db: Session) -> None:
    b.live(1 * M)
    db.refresh(b.event)
    b.event.access_expires_at = b.base + 5 * M
    db.commit()
    assert _run(db, b, 30 * M) == 0


def test_retention_run_not_alerted(b: SimpleNamespace, db: Session) -> None:
    b.live(1 * M)
    db.refresh(b.event)
    b.event.retention_completed_at = utcnow()
    db.commit()
    assert _run(db, b, 30 * M) == 0


def test_withdrawn_consent_not_alerted(b: SimpleNamespace, db: Session) -> None:
    b.live(1 * M)
    user = db.get(User, b.attendee_user.id)
    user.face_consent_version = None
    user.face_consent_at = None
    db.commit()
    assert _run(db, b, 30 * M) == 0


def test_push_payload_is_generic(b: SimpleNamespace, db: Session, apns: FakeAPNs) -> None:  # noqa: F811
    _device(db, db.get(User, b.attendee_user.id))
    b.live(1 * M)
    assert _run(db, b, 30 * M) == 1
    assert len(apns.requests) == 1
    body = json.loads(apns.requests[0].content)
    assert set(body) <= push.PAYLOAD_KEYS and set(body) == {"aps", "kind", "event_id"}
    assert body["kind"] == "new_photos" and body["event_id"] == str(b.event.id)
    assert body["aps"]["alert"] == {"title-loc-key": "push.new_photos.title", "loc-key": "push.new_photos.body"}


def test_email_has_no_counts_and_has_unsubscribe_headers(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    b.live(1 * M)
    b.live(2 * M)
    _run(db, b, 30 * M)
    (mail,) = _alerts(mailer, b)
    assert mail.subject == "New photos from Summer Party"
    assert f"/events/{b.event.id}" in mail.body and "/unsubscribe?token=" in mail.body
    assert not re.search(r"\d+\s+(new\s+)?photos?\b", mail.body + mail.subject)  # never how many
    headers = dict(mail.headers)
    assert re.fullmatch(r"<https?://[^>]+/api/alerts/unsubscribe\?token=[\w-]+>", headers["List-Unsubscribe"])
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    # The link in the email works for this user and event.
    raw = headers["List-Unsubscribe"].split("token=")[1].rstrip(">")
    assert tokens.find_alert_token(db, raw).event_id == b.event.id


def test_german_email_for_de_acceptance(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    db.add(LegalAcceptance(user_id=b.attendee_user.id, document="terms", version="x", locale="de-DE", channel="web"))
    db.commit()
    b.live(1 * M)
    _run(db, b, 30 * M)
    (mail,) = _alerts(mailer, b)
    assert mail.subject == "Neue Fotos von Summer Party"


def test_deliver_holds_no_connection(b: SimpleNamespace, db: Session, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Email and push go out after the watermarks are committed, with no pooled connection
    held (like every other sender): a slow mail server must not starve the pool."""
    b.live(1 * M)
    seen: list[int] = []
    original_send, original_push = mailer.send, push.notify_safely

    def send(mail):  # type: ignore[no-untyped-def]
        seen.append(engine.pool.checkedout() - baseline)
        original_send(mail)

    def notify(user_ids, notice):  # type: ignore[no-untyped-def]
        seen.append(engine.pool.checkedout() - baseline)
        original_push(user_ids, notice)

    monkeypatch.setattr(mailer, "send", send)
    monkeypatch.setattr(push, "notify_safely", notify)
    db.close()
    baseline = engine.pool.checkedout()
    with SessionLocal() as fresh:
        assert photo_alerts.run(fresh, b.base + 30 * M) == 1
    assert seen and set(seen) == {0}, seen


def test_deleted_account_not_alerted(b: SimpleNamespace, db: Session) -> None:
    b.live(1 * M)
    db.get(User, b.attendee_user.id).deleted_at = utcnow()
    db.commit()
    assert _run(db, b, 30 * M) == 0


def test_unverified_account_not_alerted(b: SimpleNamespace, db: Session) -> None:
    b.live(1 * M)
    db.get(User, b.attendee_user.id).email_verified_at = None
    db.commit()
    assert _run(db, b, 30 * M) == 0


def test_expired_access_stops_alerts_for_organizers_too(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    """Organizers keep their membership after the access window (to manage retention), but
    alerts are about finding photos, which ends with the window."""
    org = db.scalar(select(User).where(User.email == "org@example.com"))
    org.face_consent_version, org.face_consent_at = FACE_CONSENT_VERSION, utcnow()
    db.add(EventPhotoAlert(user_id=org.id, event_id=b.event.id, last_searched_at=b.base))
    db.commit()
    b.live(1 * M)
    db.refresh(b.event)
    b.event.access_expires_at = b.base + 5 * M
    db.commit()
    assert _run(db, b, 30 * M) == 0 and [m for m in mailer.outbox if m.to == "org@example.com"] == []


def test_no_repeat_without_new_photos(b: SimpleNamespace, db: Session, mailer: FakeMailer) -> None:
    """Once a notice covered a batch, the next day brings nothing unless more photos came."""
    b.live(1 * M)
    assert _run(db, b, 15 * M) == 1
    assert _run(db, b, 15 * M + timedelta(hours=25)) == 0
    assert len(_alerts(mailer, b)) == 1


# --- Task 5: forgetting -----------------------------------------------------------------


def _alert_data(db: Session, w: SimpleNamespace) -> tuple[int, int]:
    """(alert rows, unsubscribe tokens) of the attendee"""
    db.expire_all()
    rows = db.scalars(select(EventPhotoAlert).where(EventPhotoAlert.user_id == w.attendee_user.id)).all()
    toks = db.scalars(select(AlertToken).where(AlertToken.user_id == w.attendee_user.id)).all()
    return len(rows), len(toks)


def test_retention_deletes_alert_rows_and_tokens(w: SimpleNamespace, db: Session) -> None:
    from app.services.retention import RetentionReport, expire_event

    _search(w)
    _token(db, w)
    assert _alert_data(db, w) == (1, 1)
    expire_event(db, db.get(type(w.event), w.event.id), RetentionReport())
    assert _alert_data(db, w) == (0, 0)


def test_withdrawal_deletes_user_alert_rows_and_tokens(w: SimpleNamespace, db: Session) -> None:
    _search(w)
    _token(db, w)
    assert w.attendee.delete("/api/me/face-consent").status_code == 200
    assert _alert_data(db, w) == (0, 0)


def test_account_deletion_deletes_alert_rows_and_tokens(w: SimpleNamespace, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit deletes, not only the FK cascade (a later soft delete must not keep them)."""
    from app.services import account

    _search(w)
    _token(db, w)
    calls: list[uuid.UUID] = []
    original = photo_alerts.forget_user
    monkeypatch.setattr(photo_alerts, "forget_user", lambda db_, uid: (calls.append(uid), original(db_, uid))[1])
    account.delete_account(db, db.get(User, w.attendee_user.id))
    assert calls == [w.attendee_user.id]
    assert _alert_data(db, w) == (0, 0)
