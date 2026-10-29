"""New-photo alert settings for the current user (services/photo_alerts.py)."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DB, MemberEvent, VerifiedUser
from app.schemas.photo_alert import PhotoAlertIn, PhotoAlertOut
from app.services import photo_alerts

router = APIRouter(prefix="/api", tags=["photo_alerts"])


@router.get("/events/{event_id}/photo-alerts", response_model=PhotoAlertOut)
def get_photo_alerts(event: MemberEvent, user: VerifiedUser, db: DB) -> PhotoAlertOut:
    row = photo_alerts.get(db, user.id, event.id)
    return PhotoAlertOut(subscribed=row is not None, enabled=row is not None and row.enabled)


@router.put("/events/{event_id}/photo-alerts", response_model=PhotoAlertOut)
def set_photo_alerts(body: PhotoAlertIn, event: MemberEvent, user: VerifiedUser, db: DB) -> PhotoAlertOut:
    row = photo_alerts.get(db, user.id, event.id)
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "search_first")
    row.enabled = body.enabled
    db.commit()
    return PhotoAlertOut(subscribed=True, enabled=row.enabled)
