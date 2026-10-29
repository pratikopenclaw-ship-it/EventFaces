"""'Delete my data' (GDPR Art. 17): erase a user and everything personal tied to them."""

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.db import affected
from app.models import (
    AuthToken,
    Device,
    EventMember,
    Invite,
    LegalAcceptance,
    MatchFeedback,
    Photo,
    PhotoReport,
    PhotoStatus,
    RemovalRequest,
    SearchAudit,
    SearchGrant,
    User,
    UserRole,
)
from app.services.billing import orders as billing_orders
from app.services import photo_alerts, search_queue
from app.services.feedback import anonymize_feedback
from app.services.photo_pipeline import retire_photo


@dataclass
class DeletionSummary:
    memberships: int
    matches: int
    uploads: int
    invites: int
    searches_anonymized: int


def delete_account(db: Session, user: User) -> DeletionSummary:
    if user.role == UserRole.super_admin:
        others = db.scalar(
            select(func.count()).select_from(User).where(User.role == UserRole.super_admin, User.id != user.id)
        )
        if not others:
            raise HTTPException(status.HTTP_409_CONFLICT, "You're the only super admin; appoint another one first")

    # Photos they uploaded: remove files + embeddings, then drop the rows.
    uploads = db.scalars(select(Photo).where(Photo.uploaded_by == user.id).with_for_update()).all()
    for photo in uploads:
        if photo.status != PhotoStatus.removed:
            retire_photo(db, photo, PhotoStatus.removed)
        db.delete(photo)

    matches = affected(db.execute(delete(SearchGrant).where(SearchGrant.user_id == user.id)))
    memberships = affected(db.execute(delete(EventMember).where(EventMember.user_id == user.id)))
    invites = affected(db.execute(delete(Invite).where(Invite.email == user.email)))
    db.execute(delete(RemovalRequest).where(RemovalRequest.email == user.email))
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    db.execute(delete(Device).where(Device.user_id == user.id))  # incl. push tokens
    db.execute(delete(LegalAcceptance).where(LegalAcceptance.user_id == user.id))
    photo_alerts.forget_user(db, user.id)  # which events they searched, unsubscribe tokens
    # Keep aggregate counts for security/accountability, without the person.
    anonymize_feedback(db, MatchFeedback.user_id == user.id)
    anonymized = (
        affected(db.execute(update(SearchAudit).where(SearchAudit.user_id == user.id).values(user_id=None)))
    )
    db.execute(update(PhotoReport).where(PhotoReport.reporter_id == user.id).values(reporter_id=None))
    billing_orders.forget_user(db, user)  # orders stay (invoices), subscription ends now

    user_id = user.id
    db.delete(user)
    db.commit()
    search_queue.forget_user(user_id)  # queued-search status (a queued job re-checks and drops itself)
    return DeletionSummary(
        memberships=memberships,
        matches=matches,
        uploads=len(uploads),
        invites=invites,
        searches_anonymized=anonymized,
    )
