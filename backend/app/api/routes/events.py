import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.api.deps import DB, ManagedEvent, MemberEvent, SuperAdmin, VerifiedUser
from app.api.selfie import read_capped_body
from app.core import storage
from app.core.security import utcnow
from app.models import Event, EventVideo
from app.schemas.event import (
    EventAdminOut,
    EventCreate,
    EventListItem,
    EventPublicOut,
    EventUpdate,
    EventVideoIn,
    EventVideoOut,
)
from app.services import event_videos, imaging, search_queue
from app.services.events import generate_access_code, list_events_for, new_event, photo_counts
from app.services.retention import reopen_event
from app.workers.tasks import delete_event_objects, index_photo

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EventAdminOut)
def create_event(body: EventCreate, user: SuperAdmin, db: DB) -> Event:
    data = body.model_dump(exclude={"drive_folder"})
    event = new_event(db, **data, drive_folder_id=body.drive_folder, created_by=user.id)
    db.commit()
    return event


@router.get("", response_model=list[EventListItem])
def list_events(user: VerifiedUser, db: DB) -> list[EventListItem]:
    rows = list_events_for(db, user)
    counts = photo_counts(db, [event.id for event, _, _ in rows])
    states = search_queue.states_for(user.id, [event.id for event, _, _ in rows])
    return [
        EventListItem.model_validate(event).model_copy(
            update={
                "my_role": m.role if m else None,
                "can_manage": manage,
                "photo_count": counts.get(event.id, 0),
                "search_state": states.get(event.id),
            }
        )
        for event, m, manage in rows
    ]


@router.get("/{event_id}", response_model=EventPublicOut)
def get_event(event: MemberEvent) -> Event:
    return event


@router.get("/{event_id}/admin", response_model=EventAdminOut)
def get_event_admin(event: ManagedEvent) -> Event:
    return event


@router.patch("/{event_id}", response_model=EventAdminOut)
def update_event(body: EventUpdate, event: ManagedEvent, db: DB) -> Event:
    changes = body.model_dump(exclude_unset=True)
    if "drive_folder" in changes:
        event.drive_folder_id = changes.pop("drive_folder")
    for field in ("name", "join_mode", "moderation_mode", "description"):
        if field in changes and changes[field] is None:
            changes.pop(field)  # not nullable
    for field, value in changes.items():
        setattr(event, field, value)
    reindex: list[uuid.UUID] = []
    if event.retention_completed_at is not None and (
        event.access_expires_at is None or event.access_expires_at > utcnow()
    ):
        # Access was extended after face data was deleted: rebuild the index.
        reindex = reopen_event(db, event)
    db.commit()
    for photo_id in reindex:
        index_photo.delay(str(photo_id))
    return event


@router.post("/{event_id}/access-code/rotate", response_model=EventAdminOut)
def rotate_access_code(event: ManagedEvent, db: DB) -> Event:
    event.access_code = generate_access_code()
    db.commit()
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(user: SuperAdmin, event: ManagedEvent, db: DB) -> None:
    event_id = str(event.id)
    db.delete(event)  # cascades to members, photos, faces, sync runs
    db.commit()
    delete_event_objects.delay(event_id)


LOGO_MAX_BYTES = 1024 * 1024
_LOGO_BODY = {
    "requestBody": {
        "required": True,
        "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in ("image/png", "image/jpeg", "image/heic")},
    }
}


@router.put("/{event_id}/logo", response_model=EventAdminOut, openapi_extra=_LOGO_BODY)
async def put_logo(request: Request, event: ManagedEvent, db: DB) -> Event:
    """Raw image body (≤ 1 MB, JPEG/PNG/HEIC), re-encoded to a metadata-free PNG."""
    db.commit()  # don't hold the connection while reading and re-encoding
    data = await read_capped_body(request, LOGO_MAX_BYTES, "Logo is too large (max 1 MB)")
    try:
        png = await run_in_threadpool(imaging.process_logo, data)
    except imaging.UnsupportedImage as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    key = storage.logo_key(event.id)
    await run_in_threadpool(storage.put_png, key, png)
    event.logo_key = key
    db.commit()
    return event


@router.delete("/{event_id}/logo", response_model=EventAdminOut)
def delete_logo(event: ManagedEvent, db: DB) -> Event:
    if event.logo_key:
        storage.delete_keys(event.logo_key)
        event.logo_key = None
        db.commit()
    return event


@router.get("/{event_id}/logo", response_class=StreamingResponse)
def get_logo(event: MemberEvent) -> Response:
    if event.logo_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This event has no logo")
    body, length = storage.open_stream(event.logo_key)
    headers = {"Cache-Control": "private, max-age=300"}
    if length:
        headers["Content-Length"] = str(length)
    return StreamingResponse(body.iter_chunks(), media_type="image/png", headers=headers)


# --- Videos (organizer-added YouTube/Vimeo/Instagram/Drive links) --------------------


def _video_out(video: EventVideo) -> EventVideoOut:
    embed = event_videos.parse_embed(video.url)
    return EventVideoOut(
        id=video.id, title=video.title, url=video.url, provider=embed.provider, embed_url=embed.embed_url,
        created_at=video.created_at,
    )


@router.get("/{event_id}/videos", response_model=list[EventVideoOut])
def list_event_videos(event: MemberEvent, db: DB) -> list[EventVideoOut]:
    return [_video_out(v) for v in event_videos.list_videos(db, event)]


@router.post("/{event_id}/videos", status_code=status.HTTP_201_CREATED, response_model=EventVideoOut)
def add_event_video(body: EventVideoIn, event: ManagedEvent, db: DB) -> EventVideoOut:
    video = event_videos.add_video(db, event, body.title, body.url)
    return _video_out(video)


@router.delete("/{event_id}/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event_video(video_id: uuid.UUID, event: ManagedEvent, db: DB) -> None:
    event_videos.delete_video(db, event, video_id)
