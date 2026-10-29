"""Representative rows in every table, for migration and backup/restore drills.
Written with the ORM at the head revision; `fingerprint` hashes each table's rows so two
databases (or one database before/after a round trip) can be compared exactly."""

import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.core.security import hash_token, utcnow
from app.models import (
    AddonKind,
    AddonOrder,
    AddonOrderStatus,
    AlertToken,
    Device,
    AuthToken,
    DriveSyncRun,
    Event,
    EventMember,
    EventPhotoAlert,
    EventVideo,
    Face,
    FeedbackVerdict,
    IndexStatus,
    Invite,
    LegalAcceptance,
    Order,
    OrderKind,
    OrderStatus,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
    JoinMode,
    MatchFeedback,
    MemberRole,
    MemberStatus,
    Photo,
    PhotoReport,
    PhotoShortlist,
    PhotoSource,
    PhotoStatus,
    RemovalRequest,
    RemovalStatus,
    SearchAudit,
    SearchGrant,
    SelfieQuality,
    TokenKind,
    User,
    UserRole,
)


def populate(session: Session) -> None:
    now = utcnow()
    admin = User(email="admin@drill.example.com", password_hash="x", role=UserRole.super_admin, email_verified_at=now)
    guest = User(email="guest@drill.example.com", password_hash="x", role=UserRole.attendee, email_verified_at=now)
    session.add_all([admin, guest])
    session.flush()
    ev = Event(name="Drill Gala 🎉", slug="drill-gala-abcdef", access_code="ABCDEFGH", join_mode=JoinMode.code, drive_folder_id="1DrillFolderAAAAAAAA", created_by=admin.id)
    session.add(ev)
    session.flush()
    session.add(EventMember(event_id=ev.id, user_id=guest.id, role=MemberRole.attendee, status=MemberStatus.approved))
    photo = Photo(id=uuid.uuid4(), event_id=ev.id, source=PhotoSource.drive, drive_file_id="drill-1", original_filename="a.jpg", status=PhotoStatus.published, index_status=IndexStatus.indexed, face_count=1, indexed_at=now, published_at=now)
    upload = Photo(id=uuid.uuid4(), event_id=ev.id, source=PhotoSource.guest, uploaded_by=guest.id, original_filename="b.jpg", status=PhotoStatus.pending_review, index_status=IndexStatus.indexed)
    session.add_all([photo, upload])
    session.flush()
    face = Face(photo_id=photo.id, event_id=ev.id, bbox=[1.0, 2.0, 30.0, 40.0], det_score=0.9, embedding=[(i % 7) / 10 for i in range(512)])
    session.add(face)
    session.add(DriveSyncRun(event_id=ev.id, folder_id=ev.drive_folder_id, started_by=admin.id))
    session.flush()
    audit = SearchAudit(user_id=guest.id, event_id=ev.id, match_count=1)
    session.add(audit)
    session.flush()
    session.add(SearchGrant(user_id=guest.id, photo_id=photo.id, event_id=ev.id, similarity=0.8, face_id=face.id, search_id=audit.id, expires_at=now + timedelta(days=7)))
    session.add(MatchFeedback(search_id=audit.id, user_id=guest.id, event_id=ev.id, photo_id=photo.id, face_id=face.id, similarity_score=0.8, verdict=FeedbackVerdict.me))
    session.add(SelfieQuality(event_id=ev.id, search_id=audit.id, shot="front", passed=True, score=87, width=640, height=480, face_count=1, det_score=0.9, face_height_ratio=0.4, yaw=1.0))
    session.add(Invite(event_id=ev.id, email="friend@drill.example.com", token_hash=hash_token("drill-invite"), expires_at=now + timedelta(days=3)))
    session.add(PhotoReport(photo_id=photo.id, event_id=ev.id, reporter_id=guest.id, reason="other"))
    session.add(RemovalRequest(event_id=ev.id, email="stranger@drill.example.com", token_hash=hash_token("drill-removal"), status=RemovalStatus.submitted, matched_photo_ids=[photo.id]))
    session.add(AuthToken(user_id=guest.id, kind=TokenKind.refresh, token_hash=hash_token("drill-refresh"), expires_at=now + timedelta(days=1), session_id=uuid.uuid4()))
    # An app user: passwordless account with a device-bound session.
    app_user = User(email="app@drill.example.com", password_hash=None, email_verified_at=now)
    session.add(app_user)
    session.flush()
    session.add(Device(user_id=app_user.id, session_id=uuid.uuid4(), name="Drill iPhone", platform="ios", app_version="1.0.0", public_key="B" + "A" * 87))
    # Proof of acceptance of the Terms of Use (the history table; users.terms_version is a
    # cache that a downgrade below 0013 drops, so it isn't "surviving data").
    session.add(LegalAcceptance(user_id=app_user.id, document="terms", version="2026-10-03", locale="de", channel="ios"))
    # Billing (0014): a subscription, a paid order and a processed provider event.
    sub = Subscription(user_id=admin.id, plan="pro", status=SubscriptionStatus.active, current_period_start=now, current_period_end=now)
    session.add(sub)
    session.flush()
    session.add(Order(user_id=admin.id, plan="pro", kind=OrderKind.subscription, amount_cents=19900, currency="EUR", vat_rate=19, status=OrderStatus.paid, provider="fake", provider_ref="drill-session", subscription_id=sub.id, paid_at=now))
    session.add(WebhookEvent(provider="fake", provider_event_id="evt_drill"))
    # Event videos (0015): an organizer-added YouTube link on the event's Videos tab.
    session.add(EventVideo(event_id=ev.id, title="Highlights", url="https://youtu.be/dQw4w9WgXcQ"))
    # Photo shortlists (0016): an attendee's personal pick.
    session.add(PhotoShortlist(user_id=guest.id, photo_id=photo.id, event_id=ev.id))
    # Add-on orders (0020): a pending per-photo purchase.
    session.add(
        AddonOrder(
            buyer_user_id=guest.id,
            event_id=ev.id,
            kind=AddonKind.human_edit,
            photo_ids=[photo.id],
            amount_cents=999,
            currency="EUR",
            vat_rate=19,
            status=AddonOrderStatus.pending,
            provider="fake",
            provider_ref="drill-addon-session",
        )
    )
    # New-photo alerts (0021): an attendee's subscription after a search, and an unsubscribe token.
    session.add(EventPhotoAlert(user_id=guest.id, event_id=ev.id, last_searched_at=now))
    session.add(AlertToken(token_hash=hash_token("drill-alert"), user_id=guest.id, event_id=ev.id, expires_at=now + timedelta(days=30)))
    session.commit()


def tables(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version' ORDER BY 1")
        ).scalars()
    )


def fingerprint(conn: Connection) -> dict[str, tuple[int, str]]:
    """{table: (row count, md5 of all rows in a stable order)}."""
    out = {}
    for t in tables(conn):
        rows = conn.execute(text(f'SELECT t::text FROM "{t}" t ORDER BY 1')).scalars().all()  # noqa: S608 - names from pg_tables
        out[t] = (len(rows), hashlib.md5("\n".join(rows).encode(), usedforsecurity=False).hexdigest())
    return out
