"""Removal requests from people who appear in event photos (they may not be users).

1. create:   requester gives event + email (+ message) → verification link by email
2. submit:   via the link, optionally with a reference selfie. The selfie is matched in
             memory against *that event only* and discarded; only photo IDs are kept.
             The requester is never shown the matches (they could be a stranger
             fishing for photos of someone else) — organizers review them.
3. resolve:  organizer removes some/all matched (or other) photos, or declines.
"""

import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import Mail, get_mailer
from app.core.security import hash_token, new_opaque_token, utcnow
from app.models import (
    Event,
    EventMember,
    MemberRole,
    MemberStatus,
    Photo,
    PhotoStatus,
    RemovalRequest,
    RemovalStatus,
    User,
    UserRole,
)
from app.services.photo_pipeline import retire_photo
from app.services.search import search_faces, selfie_embedding


def create_request(db: Session, event: Event, email: str, message: str) -> str:
    raw = new_opaque_token()
    db.add(RemovalRequest(event_id=event.id, email=email, message=message, token_hash=hash_token(raw)))
    db.commit()
    return raw


def request_link(raw: str) -> str:
    return f"{get_settings().frontend_url}/removal/{raw}"


def find_open_request(db: Session, raw: str) -> RemovalRequest:
    req = db.scalar(select(RemovalRequest).where(RemovalRequest.token_hash == hash_token(raw)).with_for_update())
    max_age = timedelta(hours=get_settings().removal_token_hours)
    if req is None or req.status != RemovalStatus.unverified or req.created_at < utcnow() - max_age:
        raise HTTPException(status.HTTP_410_GONE, "This link is invalid, expired or was already used")
    return req


def submit(db: Session, req: RemovalRequest, selfie: bytes | None) -> int:
    matched: list[uuid.UUID] = []
    if selfie is not None:
        embedding = selfie_embedding(selfie)
        try:
            # Threshold a bit lower than search: here false positives only cost an
            # organizer a glance, while misses leave someone's photo online.
            threshold = max(0.0, get_settings().face_match_threshold - 0.05)
            matches = search_faces(db, event_id=req.event_id, embedding=embedding, threshold=threshold, limit=500)
        finally:
            del embedding
        matched = [m.photo_id for m in matches]
    req.matched_photo_ids = matched
    req.status = RemovalStatus.submitted
    req.verified_at = utcnow()
    db.commit()
    return len(matched)


def organizer_emails(db: Session, event_id: uuid.UUID) -> list[str]:
    organizers = db.scalars(
        select(User.email)
        .join(EventMember, EventMember.user_id == User.id)
        .where(
            EventMember.event_id == event_id,
            EventMember.role == MemberRole.organizer,
            EventMember.status == MemberStatus.approved,
        )
    ).all()
    return list(organizers) or list(db.scalars(select(User.email).where(User.role == UserRole.super_admin)))


def resolve(
    db: Session, event: Event, req: RemovalRequest, user: User, action: str, photo_ids: list[uuid.UUID] | None
) -> int:
    if req.status != RemovalStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request isn't awaiting review")
    removed = 0
    if action == "remove":
        ids = photo_ids if photo_ids is not None else list(req.matched_photo_ids)
        photos = db.scalars(
            select(Photo)
            .where(Photo.id.in_(ids), Photo.event_id == event.id, Photo.status != PhotoStatus.removed)
            .with_for_update()
        ).all()
        for photo in photos:
            retire_photo(db, photo, PhotoStatus.removed)
        removed = len(photos)
        req.status = RemovalStatus.resolved
    else:
        req.status = RemovalStatus.declined
    req.resolved_at = utcnow()
    req.resolved_by = user.id
    db.commit()

    outcome = (
        f"The organizers removed {removed} photo{'s' if removed != 1 else ''} from {event.name}."
        if action == "remove"
        else f"The organizers of {event.name} reviewed your request and did not remove any photos. "
        "Reply to them directly if you think this is a mistake."
    )
    get_mailer().send(Mail(to=req.email, subject=f"Your removal request for {event.name}", body=outcome + "\n"))
    return removed
