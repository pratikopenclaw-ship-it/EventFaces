"""New-photo alerts (Part 1): attendees who searched an event hear when new photos with
faces go live there, so they scan again. Nothing biometric is stored: a search only leaves
an `event_photo_alerts` row saying when the user last searched the event
(docs/superpowers/specs/2026-10-20-new-photo-alerts-design.md). Rows never reach organizer
or admin views."""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import Mail, get_mailer
from app.models import Event, EventMember, EventPhotoAlert, LegalAcceptance, Photo, PhotoStatus, User
from app.services import membership, push, tokens

log = logging.getLogger(__name__)

RECENT = timedelta(days=7)  # only events with photos this recent are looked at
TOKEN_MAX_AGE = timedelta(days=180)  # unsubscribe links work this long at most


def _qualifying_after(event_id: uuid.UUID, since: datetime):  # type: ignore[no-untyped-def]
    """Live photos with faces that went live after `since` (faceless photos never count)."""
    return (
        Photo.event_id == event_id,
        Photo.status == PhotoStatus.published,
        Photo.face_count > 0,
        Photo.published_at > since,
    )


def record_search(db: Session, user_id: uuid.UUID, event_id: uuid.UUID, now: datetime) -> None:
    """Subscribe on search (or move the watermark on). Keeps an earlier opt-out. No commit."""
    stmt = insert(EventPhotoAlert).values(user_id=user_id, event_id=event_id, last_searched_at=now)
    db.execute(stmt.on_conflict_do_update(index_elements=["user_id", "event_id"], set_={"last_searched_at": now}))


def get(db: Session, user_id: uuid.UUID, event_id: uuid.UUID) -> EventPhotoAlert | None:
    return db.get(EventPhotoAlert, (user_id, event_id))


def has_new_photos(db: Session, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    """The banner: qualifying photos went live after the user's last search. Independent of
    the notification watermark and the opt-outs (it only shows inside the app)."""
    row = get(db, user_id, event_id)
    if row is None:
        return False
    return bool(db.scalar(select(exists().where(*_qualifying_after(event_id, row.last_searched_at)))))


def unsubscribe(db: Session, raw_token: str, scope: str) -> None:
    """Email link: stop this event's alerts ("event") or all alerts ("all") for the token's
    user. Unknown or expired tokens change nothing and are not reported. No commit."""
    token = tokens.find_alert_token(db, raw_token)
    if token is None:
        return
    if scope == "all":
        user = db.get(User, token.user_id)
        if user is not None:
            user.new_photo_alerts = False
        return
    row = get(db, token.user_id, token.event_id)
    if row is not None:
        row.enabled = False


# --- sending -------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingAlert:
    user_id: uuid.UUID
    event_id: uuid.UUID
    email: str
    event_name: str
    locale: Literal["en", "de"]
    unsubscribe_token: str


def _locale(db: Session, user_id: uuid.UUID) -> Literal["en", "de"]:
    """The language the user last accepted legal texts in (no locale column exists)."""
    newest = db.scalar(
        select(LegalAcceptance.locale)
        .where(LegalAcceptance.user_id == user_id)
        .order_by(LegalAcceptance.accepted_at.desc())
        .limit(1)
    )
    return "de" if newest and newest.lower().startswith("de") else "en"


def _event_open(event: Event, now: datetime) -> bool:
    return (
        event.notify_new_photos
        and event.retention_completed_at is None
        and (event.access_expires_at is None or event.access_expires_at > now)
    )


def _user_eligible(user: User | None, consent_version: str) -> bool:
    return (
        user is not None
        and user.deleted_at is None
        and user.email_verified_at is not None
        and user.new_photo_alerts
        and user.face_consent_version == consent_version
    )


def collect_due(db: Session, now: datetime) -> list[PendingAlert]:
    """Pick everyone due a notice, move their watermarks on and commit. Sending happens
    afterwards in deliver(), with no connection held; a crash in between loses a notice
    rather than sending one twice."""
    from app.services.search import FACE_CONSENT_VERSION  # search imports this module

    settings = get_settings()
    quiet_edge = now - timedelta(minutes=settings.new_photo_alert_quiet_minutes)
    interval = timedelta(hours=settings.new_photo_alert_min_interval_hours)
    live = (Photo.status == PhotoStatus.published, Photo.face_count > 0, Photo.published_at <= now)
    # Cheap first pass: only events with a recent qualifying photo.
    event_ids = db.scalars(
        select(Photo.event_id).where(*live, Photo.published_at > now - RECENT).distinct()
    ).all()
    due: list[PendingAlert] = []
    for event_id in event_ids:
        event = db.get(Event, event_id)
        if event is None or not _event_open(event, now):
            continue
        newest = db.scalar(select(func.max(Photo.published_at)).where(Photo.event_id == event_id, *live))
        if newest is None or newest > quiet_edge:
            continue  # the upload burst may still be going on: wait until it's quiet
        rows = db.scalars(
            select(EventPhotoAlert)
            .where(EventPhotoAlert.event_id == event_id, EventPhotoAlert.enabled.is_(True))
            .with_for_update()
        ).all()
        for row in rows:
            if row.last_notified_at is not None and row.last_notified_at > now - interval:
                continue
            since = max(row.last_searched_at, row.notified_through or row.last_searched_at)
            through = db.scalar(
                select(func.max(Photo.published_at)).where(Photo.event_id == event_id, *live, Photo.published_at > since)
            )
            if through is None:
                continue
            user = db.get(User, row.user_id)
            if not _user_eligible(user, FACE_CONSENT_VERSION):
                continue
            member = db.scalar(select(EventMember).where(EventMember.event_id == event_id, EventMember.user_id == row.user_id))
            if not membership.is_active_member(event, member):
                continue
            expires = min(event.access_expires_at or now + TOKEN_MAX_AGE, now + TOKEN_MAX_AGE)
            raw = tokens.issue_alert_token(db, row.user_id, event_id, expires)
            row.last_notified_at = now
            row.notified_through = through
            due.append(PendingAlert(row.user_id, event_id, user.email, event.name, _locale(db, row.user_id), raw))
    db.commit()
    return due


_TEXT = {
    "en": (
        "New photos from {event}",
        "New photos were added to {event}. Scan again to see if you're in them:\n{link}\n\n"
        "You're getting this because you searched for your photos at this event. "
        "Stop these emails for this event: {unsubscribe}\n",
    ),
    "de": (
        "Neue Fotos von {event}",
        "Zu {event} wurden neue Fotos hinzugefügt. Scanne noch einmal, um zu sehen, ob du darauf bist:\n{link}\n\n"
        "Du bekommst diese E-Mail, weil du bei diesem Event nach deinen Fotos gesucht hast. "
        "Diese E-Mails für dieses Event abbestellen: {unsubscribe}\n",
    ),
}


def _mail(alert: PendingAlert) -> Mail:
    """Event name and links only: never how many photos or which (we don't know if the
    person is in them)."""
    base = get_settings().frontend_url.rstrip("/")
    subject, body = _TEXT[alert.locale]
    link = f"{base}/events/{alert.event_id}"
    unsubscribe = f"{base}/unsubscribe?token={alert.unsubscribe_token}"
    return Mail(
        to=alert.email,
        subject=subject.format(event=alert.event_name),
        body=body.format(event=alert.event_name, link=link, unsubscribe=unsubscribe),
        headers=(
            ("List-Unsubscribe", f"<{base}/api/alerts/unsubscribe?token={alert.unsubscribe_token}>"),
            ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"),
        ),
    )


def deliver(alerts: list[PendingAlert]) -> None:
    """Send what collect_due committed. Uses no DB session (push opens its own briefly);
    one failure never stops the rest."""
    by_event: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for alert in alerts:
        try:
            get_mailer().send(_mail(alert))
        except Exception as e:  # noqa: BLE001 - a mail outage must not stop the batch
            log.warning("New-photo alert email failed: %s", type(e).__name__)
        by_event[alert.event_id].append(alert.user_id)
    for event_id, user_ids in by_event.items():
        push.notify_safely(user_ids, push.Notice("new_photos", event_id))


def run(db: Session, now: datetime) -> int:
    alerts = collect_due(db, now)
    deliver(alerts)
    return len(alerts)
