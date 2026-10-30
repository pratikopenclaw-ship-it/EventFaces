"""Scheduled data minimisation (GDPR Art. 5(1)(c),(e)). Run hourly by Celery beat.

Every step is idempotent; `run_retention` returns counts for logging.

| Data                               | Kept until                                            |
|------------------------------------|-------------------------------------------------------|
| Face embeddings of an event        | event access ends (`access_expires_at`)               |
| Photos of an event (optional)      | access ends, if `delete_photos_on_expiry`             |
| Search grants (user ↔ matched photo)| SEARCH_GRANT_DAYS or access end, whichever first     |
| Search audit + selfie quality rows | AUDIT_RETENTION_DAYS (default 365)                    |
| Match feedback links (user/face)   | anonymized when the event's face data is deleted      |
| Removal requests                   | unverified: REMOVAL_TOKEN_HOURS; closed: REMOVAL_REQUEST_RETENTION_DAYS |
| Never-verified accounts            | UNVERIFIED_USER_DAYS (default 14)                     |
| Used/expired auth tokens           | 30 days                                               |
"""

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import affected
from app.core.security import utcnow
from app.models import (
    AlertToken,
    AuthToken,
    Event,
    Face,
    Invite,
    InviteStatus,
    MatchFeedback,
    Photo,
    PhotoStatus,
    RemovalRequest,
    RemovalStatus,
    SearchAudit,
    SearchGrant,
    SelfieQuality,
    User,
)
from app.services import photo_alerts
from app.services.feedback import anonymize_feedback
from app.services.photo_pipeline import retire_photo

log = logging.getLogger(__name__)


@dataclass
class RetentionReport:
    events_expired: int = 0
    faces_deleted: int = 0
    photos_deleted: int = 0
    grants_deleted: int = 0
    invites_revoked: int = 0
    audit_rows_deleted: int = 0
    removal_requests_deleted: int = 0
    unverified_users_deleted: int = 0
    tokens_deleted: int = 0
    feedback_anonymized: int = 0
    quality_rows_deleted: int = 0
    alert_tokens_deleted: int = 0


def expire_event(db: Session, event: Event, report: RetentionReport) -> None:
    """Delete biometric data (and optionally photos) of one event whose access has ended."""
    report.faces_deleted += affected(db.execute(delete(Face).where(Face.event_id == event.id)))
    report.feedback_anonymized += anonymize_feedback(db, MatchFeedback.event_id == event.id)
    report.grants_deleted += affected(db.execute(delete(SearchGrant).where(SearchGrant.event_id == event.id)))
    photo_alerts.forget_event(db, event.id)  # who searched it (new-photo alerts)
    report.invites_revoked += (
        affected(db.execute(
            update(Invite)
            .where(Invite.event_id == event.id, Invite.status == InviteStatus.pending)
            .values(status=InviteStatus.revoked)
        ))
    )
    if event.delete_photos_on_expiry:
        photos = db.scalars(
            select(Photo)
            .where(Photo.event_id == event.id, Photo.status != PhotoStatus.removed)
            .with_for_update()
        ).all()
        for photo in photos:
            retire_photo(db, photo, PhotoStatus.removed)
        report.photos_deleted += len(photos)
    else:
        # Photos stay, but nothing is indexed any more.
        db.execute(update(Photo).where(Photo.event_id == event.id).values(face_count=0))
    event.retention_completed_at = utcnow()
    report.events_expired += 1
    db.commit()


def run_retention(db: Session, now: datetime | None = None) -> RetentionReport:
    s = get_settings()
    now = now or utcnow()
    report = RetentionReport()

    due = db.scalars(
        select(Event).where(Event.access_expires_at <= now, Event.retention_completed_at.is_(None))
    ).all()
    for event in due:
        expire_event(db, event, report)

    report.grants_deleted += affected(db.execute(delete(SearchGrant).where(SearchGrant.expires_at <= now)))
    report.audit_rows_deleted = (
        affected(db.execute(
            delete(SearchAudit).where(SearchAudit.created_at < now - timedelta(days=s.audit_retention_days))
        ))
    )
    report.quality_rows_deleted = (
        affected(db.execute(
            delete(SelfieQuality).where(SelfieQuality.created_at < now - timedelta(days=s.audit_retention_days))
        ))
    )
    report.removal_requests_deleted = (
        affected(db.execute(
            delete(RemovalRequest).where(
                (
                    (RemovalRequest.status == RemovalStatus.unverified)
                    & (RemovalRequest.created_at < now - timedelta(hours=s.removal_token_hours))
                )
                | (
                    RemovalRequest.status.in_([RemovalStatus.resolved, RemovalStatus.declined])
                    & (RemovalRequest.resolved_at < now - timedelta(days=s.removal_request_retention_days))
                )
            )
        ))
    )
    report.unverified_users_deleted = (
        affected(db.execute(
            delete(User).where(
                User.email_verified_at.is_(None),
                User.created_at < now - timedelta(days=s.unverified_user_days),
            )
        ))
    )
    report.tokens_deleted = (
        affected(db.execute(
            delete(AuthToken).where(
                (AuthToken.expires_at < now - timedelta(days=30))
                | (AuthToken.used_at < now - timedelta(days=30))
            )
        ))
    )
    # Unsubscribe links record who searched an event: gone once expired, also for events
    # that never expire.
    report.alert_tokens_deleted = affected(db.execute(delete(AlertToken).where(AlertToken.expires_at <= now)))
    db.commit()
    # Logged on every run (not only when something was deleted): operators alert on a
    # missing hourly line, since retention is a GDPR duty (DEPLOYMENT.md, monitoring).
    log.info("Retention run: %s", asdict(report))
    return report


def reopen_event(db: Session, event: Event) -> list[uuid.UUID]:
    """Access was extended after retention ran: allow re-indexing. Returns photo IDs to index."""
    event.retention_completed_at = None
    ids = list(
        db.scalars(
            select(Photo.id).where(
                Photo.event_id == event.id,
                Photo.status.in_([PhotoStatus.published, PhotoStatus.pending_review]),
                Photo.original_key.is_not(None),
            )
        )
    )
    return ids
