"""New-photo alert settings for the current user (services/photo_alerts.py)."""

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import DB, MemberEvent, VerifiedUser
from app.core import rate_limit
from app.schemas.auth import MessageOut
from app.schemas.photo_alert import PhotoAlertIn, PhotoAlertOut, UnsubscribeIn
from app.services import photo_alerts

MAX_UNSUBSCRIBE_BYTES = 1024
ONE_CLICK_BODY = b"List-Unsubscribe=One-Click"  # RFC 8058

UNSUBSCRIBE_OPENAPI: dict[str, object] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": UnsubscribeIn.model_json_schema()},
            "application/x-www-form-urlencoded": {
                "schema": {"type": "object", "properties": {"List-Unsubscribe": {"type": "string", "enum": ["One-Click"]}}}
            },
        },
    }
}

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


@router.post("/alerts/unsubscribe", response_model=MessageOut, openapi_extra=UNSUBSCRIBE_OPENAPI)
async def unsubscribe(request: Request, db: DB, token: str | None = Query(default=None, max_length=200)) -> MessageOut:
    """Stop new-photo alerts from an email link, without a login: authorized only by the
    link's token (services/tokens.find_alert_token). Accepts the page's JSON body
    {token, scope} or a mail provider's RFC 8058 one-click form POST to the header URL
    (?token=..., scope "event"). Always answers ok, so it tells nothing about tokens or
    accounts. CSRF-exempt only without auth cookies (api/csrf.py); GET is not allowed, so
    link scanners can't unsubscribe anyone."""
    rate_limit.enforce(f"alerts-unsub:{rate_limit.client_ip(request)}", rate_limit.Limit(30, 3600))
    if int(request.headers.get("content-length") or 0) > MAX_UNSUBSCRIBE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Too large")
    raw = await request.body()
    if len(raw) > MAX_UNSUBSCRIBE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Too large")
    if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        if raw.strip() != ONE_CLICK_BODY or not token:
            raise RequestValidationError([{"type": "value_error", "loc": ("body",), "msg": "Not a one-click unsubscribe", "input": None}])
        body = UnsubscribeIn(token=token, scope="event")
    else:
        try:
            body = UnsubscribeIn.model_validate_json(raw)
        except ValidationError as e:
            raise RequestValidationError(e.errors()) from None
    await run_in_threadpool(_unsubscribe, db, body)
    return MessageOut(detail="ok")


def _unsubscribe(db: Session, body: UnsubscribeIn) -> None:
    photo_alerts.unsubscribe(db, body.token, body.scope)
    db.commit()
