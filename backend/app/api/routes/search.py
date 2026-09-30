from collections.abc import Iterator
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from zipstream import ZIP_STORED, ZipStream

from app.api.deps import DB, CurrentUser, ManagedEvent, MemberEvent, SuperAdmin, VerifiedUser
from app.api.selfie import is_selfie_set, read_selfie, read_selfie_set, selfie_content_type
from app.core import face_slots, rate_limit, storage
from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Event, FeedbackVerdict, MatchFeedback, Photo, PhotoStatus, SearchGrant, User
from app.schemas.search import (
    BandOut,
    CaptureTokenOut,
    ConsentIn,
    ConsentInfo,
    DownloadIn,
    DownloadOut,
    EventMatchQualityOut,
    FeedbackIn,
    GlobalMatchQualityOut,
    MatchOut,
    MatchQualityOut,
    MyPhotoOut,
    SearchOut,
    SelfieRejectionOut,
    ShotQualityOut,
)
from app.services import capture_tokens, downloads, search_queue
from app.services.feedback import MatchQuality, anonymize_feedback, match_quality, record_missing, record_verdict
from app.services.membership import can_access
from app.services.photo_access import viewable_photos
from app.services.search import FACE_CONSENT_VERSION, SelfieRejected, run_search
from app.services.selfie_quality import SHOTS_CAMERA

router = APIRouter(prefix="/api", tags=["search"])

# --- Consent -------------------------------------------------------------------


def _consent_info(user: User) -> ConsentInfo:
    return ConsentInfo(
        version=FACE_CONSENT_VERSION,
        grant_days=get_settings().search_grant_days,
        given=user.face_consent_version == FACE_CONSENT_VERSION,
        given_at=user.face_consent_at if user.face_consent_version == FACE_CONSENT_VERSION else None,
    )


@router.get("/me/face-consent", response_model=ConsentInfo)
def get_consent(user: CurrentUser) -> ConsentInfo:
    return _consent_info(user)


@router.post("/me/face-consent", response_model=ConsentInfo)
def give_consent(body: ConsentIn, user: VerifiedUser, db: DB) -> ConsentInfo:
    if body.version != FACE_CONSENT_VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT, "The consent text has changed; please review it again")
    user.face_consent_at = utcnow()
    user.face_consent_version = FACE_CONSENT_VERSION
    db.commit()
    return _consent_info(user)


@router.delete("/me/face-consent", response_model=ConsentInfo)
def withdraw_consent(user: CurrentUser, db: DB) -> ConsentInfo:
    """Withdrawal stops future searches, forgets past results (grants) and unlinks
    the user's match feedback from them."""
    user.face_consent_at = None
    user.face_consent_version = None
    db.execute(delete(SearchGrant).where(SearchGrant.user_id == user.id))
    anonymize_feedback(db, MatchFeedback.user_id == user.id)
    db.commit()
    return _consent_info(user)


# --- Search --------------------------------------------------------------------


def _require_consent(user: User) -> None:
    if user.face_consent_version != FACE_CONSENT_VERSION:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "consent_required")


def upload_allowed(event: Event) -> bool:
    """File selfies need BOTH the global switch and the event's setting."""
    return get_settings().allow_selfie_file_upload and event.allow_selfie_file_upload


@router.get("/selfie-requirements")
def selfie_requirements(user: CurrentUser) -> dict[str, float | int | bool]:
    """The server's quality thresholds, so the browser's live guidance matches them."""
    s = get_settings()
    return {
        "min_width": s.selfie_min_width,
        "min_height": s.selfie_min_height,
        "face_height_min": s.selfie_face_height_min,
        "face_height_max": s.selfie_face_height_max,
        "max_yaw": s.selfie_max_yaw,
        "max_pitch": s.selfie_max_pitch,
        "max_roll": s.selfie_max_roll,
        "front_max_yaw": s.selfie_front_max_yaw,
        "side_min_yaw": s.selfie_side_min_yaw,
        "min_brightness": s.selfie_min_brightness,
        "max_brightness": s.selfie_max_brightness,
        "capture_token_seconds": s.capture_token_seconds,
        "global_file_upload": s.allow_selfie_file_upload,
    }


@router.post("/events/{event_id}/capture-token", response_model=CaptureTokenOut)
def capture_token(request: Request, event: MemberEvent, user: VerifiedUser) -> CaptureTokenOut:
    """Issued when the guided camera flow starts; valid once, for 60 s, for this user+event."""
    _require_consent(user)
    rate_limit.enforce(f"captok:{user.id}", rate_limit.Limit(30, 600))
    return CaptureTokenOut(token=capture_tokens.issue(user.id, event.id), expires_in=get_settings().capture_token_seconds)


@router.post(
    "/events/{event_id}/search",
    response_model=SearchOut,
    responses={422: {"model": SelfieRejectionOut, "description": "A selfie failed the quality gate"}},
)
async def search(
    request: Request,
    event: MemberEvent,
    user: VerifiedUser,
    db: DB,
    source: Literal["camera", "upload"] = "camera",
) -> SearchOut:
    _require_consent(user)
    # Waiting for a slot must not hold the pooled connection the auth checks opened (SEC-038).
    db.commit()
    # Take a face-work slot first (SEC-039). If none frees up in time, the search can still
    # be queued ("we'll notify you"); only when the queue is full is it turned away, and
    # then before its selfies are read into memory or its search budget is spent.
    s = get_settings()
    got_slot = await face_slots.acquire(s.search_queue_wait_seconds)
    try:
        if not got_slot:
            try:
                search_queue.check_can_queue(user.id, event.id)
            except search_queue.QueueFull as e:
                raise face_slots.BUSY from e
            except search_queue.AlreadyQueued as e:
                raise HTTPException(status.HTTP_409_CONFLICT, "Your earlier search is still queued. We'll email you when it's done.") from e

        limit = rate_limit.Limit.parse(s.search_rate_limit)
        rate_limit.enforce(f"search:user:{user.id}", limit)
        rate_limit.enforce(f"search:ip:{rate_limit.client_ip(request)}", rate_limit.Limit(limit.count * 3, limit.seconds))
        shots = await _read_validated_shots(request, event, user, source)
        # Counted only for requests that passed every check, so invalid requests from one
        # member can't burn the event's budget for everyone else.
        rate_limit.enforce(f"search:event:{event.id}", rate_limit.Limit.parse(s.search_event_rate_limit))

        if not got_slot:
            try:
                search_queue.enqueue(user.id, event.id, shots)  # selfies stay in this process's memory
            except search_queue.QueueFull as e:
                raise face_slots.BUSY from e
            except search_queue.AlreadyQueued as e:
                raise HTTPException(status.HTTP_409_CONFLICT, "Your earlier search is still queued.") from e
            finally:
                del shots
            return JSONResponse(  # type: ignore[return-value]  # 202 bypasses response_model by design
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "queued": True,
                    "detail": "We're busy right now. We'll email you and show your photos here when they're ready.",
                    "expires_in": s.search_queue_ttl_seconds,
                },
            )

        # End the transaction opened by the auth checks so the pooled connection is free while
        # the face model runs (seconds, serialized): run_search does all face analysis before
        # its first query. Holding it let ~15 concurrent searches starve every other endpoint.
        db.commit()
        try:
            # Face analysis and DB work block; keep them off the event loop.
            result: SearchOut | JSONResponse = await run_in_threadpool(_search_sync, db, user, event, shots)
            return result  # type: ignore[return-value]  # a JSONResponse (422) bypasses response_model by design
        finally:
            del shots
    finally:
        if got_slot:
            face_slots.release()


async def _read_validated_shots(request: Request, event: Event, user: User, source: str) -> list[tuple[str, bytes]]:
    if source == "camera":
        # Camera searches must come from the guided capture flow: exactly front, left, right.
        token = request.headers.get("x-capture-token", "")
        if not token or not capture_tokens.consume(token, user.id, event.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "capture_token_invalid")
        if not is_selfie_set(request):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Camera searches send a set of three selfies")
        shots = await read_selfie_set(request)
        if [shot for shot, _ in shots] != list(SHOTS_CAMERA):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Expected front, left and right selfies")
        return shots
    if not upload_allowed(event):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This event requires a live camera selfie")
    if is_selfie_set(request):
        return [("any", data) for _, data in await read_selfie_set(request)]
    if selfie_content_type(request):
        return [("any", await read_selfie(request))]
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send the selfie as a JPEG, PNG or HEIC image")


@router.get("/events/{event_id}/search-status")
def search_status(event: MemberEvent, user: VerifiedUser) -> dict[str, Any]:
    """The caller's queued search for this event: none | queued | done | rejected | cancelled | expired."""
    record = search_queue.get_status(user.id, event.id)
    return {k: record.get(k) for k in ("state", "queued_at", "updated_at", "match_count", "message", "shot", "code")}


def _search_sync(db: Session, user: User, event: Event, shots: list[tuple[str, bytes]]) -> SearchOut | JSONResponse:
    try:
        outcome = run_search(db, user, event, shots)
    except SelfieRejected as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": e.message, "code": e.code, "shot": e.shot},
        )
    sizes = {
        pid: (w, h)
        for pid, w, h in db.execute(
            select(Photo.id, Photo.width, Photo.height).where(Photo.id.in_([m.photo_id for m in outcome.matches]))
        )
    }
    return SearchOut(
        search_id=outcome.search_id,
        matches=[
            MatchOut(
                id=m.photo_id,
                similarity=round(m.similarity, 3),
                tier=m.tier,
                width=sizes[m.photo_id][0],
                height=sizes[m.photo_id][1],
            )
            for m in outcome.matches
            if m.photo_id in sizes
        ],
        quality=[ShotQualityOut(shot=r.shot, score=r.score) for r in outcome.quality],
    )


@router.get("/events/{event_id}/my-photos", response_model=list[MyPhotoOut])
def my_photos(event: MemberEvent, user: VerifiedUser, db: DB) -> list[MyPhotoOut]:
    """Photos this user matched earlier (until the grant expires) or uploaded."""
    best = get_settings().match_best_threshold
    rows = db.execute(
        select(Photo, SearchGrant, MatchFeedback.verdict)
        .outerjoin(
            SearchGrant,
            (SearchGrant.photo_id == Photo.id)
            & (SearchGrant.user_id == user.id)
            & (SearchGrant.expires_at > utcnow()),
        )
        .outerjoin(MatchFeedback, (MatchFeedback.photo_id == Photo.id) & (MatchFeedback.user_id == user.id))
        .where(
            Photo.event_id == event.id,
            Photo.status == PhotoStatus.published,
            (SearchGrant.photo_id.is_not(None)) | (Photo.uploaded_by == user.id),
        )
        .order_by(SearchGrant.similarity.desc().nulls_last(), Photo.created_at.desc())
    ).all()
    return [
        MyPhotoOut(
            id=p.id,
            width=p.width,
            height=p.height,
            similarity=round(g.similarity, 3) if g else None,
            tier=("best" if g.similarity >= best else "possible") if g else None,
            verdict=verdict.value if verdict and verdict != FeedbackVerdict.missing else None,
            expires_at=g.expires_at if g else None,
        )
        for p, g, verdict in rows
    ]


# --- Match feedback --------------------------------------------------------------


@router.post("/events/{event_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def give_feedback(body: FeedbackIn, event: MemberEvent, user: VerifiedUser, db: DB) -> None:
    rate_limit.enforce(f"feedback:{user.id}", rate_limit.Limit(300, 3600))
    record_verdict(db, user, event, body.photo_id, FeedbackVerdict(body.verdict))


@router.post("/events/{event_id}/feedback/missing", status_code=status.HTTP_204_NO_CONTENT)
def report_missing(event: MemberEvent, user: VerifiedUser, db: DB) -> None:
    rate_limit.enforce(f"feedback-missing:{user.id}:{event.id}", rate_limit.Limit(3, 86400))
    record_missing(db, user, event)


def _quality_out(q: MatchQuality) -> MatchQualityOut:
    data = asdict(q)
    data["bands"] = [BandOut(**asdict(b), wrong_rate=b.wrong_rate) for b in q.bands]
    return MatchQualityOut(**data)


@router.get("/events/{event_id}/match-quality", response_model=MatchQualityOut)
def event_match_quality(event: ManagedEvent, db: DB) -> MatchQualityOut:
    return _quality_out(match_quality(db, event.id))


@router.get("/admin/match-quality", response_model=GlobalMatchQualityOut)
def global_match_quality(user: SuperAdmin, db: DB) -> GlobalMatchQualityOut:
    overall = match_quality(db, None)
    events = []
    for ev in db.scalars(select(Event).order_by(Event.created_at.desc())):
        q = match_quality(db, ev.id)
        if not q.searches and not q.feedback:
            continue
        me = sum(b.me for b in q.bands)
        rated = sum(b.total for b in q.bands)
        events.append(
            EventMatchQualityOut(
                event_id=ev.id,
                event_name=ev.name,
                searches=q.searches,
                feedback=q.feedback,
                wrong_rate=round(1 - me / rated, 3) if rated else None,
                missing_reports=q.missing_reports,
            )
        )
    return GlobalMatchQualityOut(**_quality_out(overall).model_dump(), events=events)


# --- Downloads -----------------------------------------------------------------


@router.post("/events/{event_id}/downloads", response_model=DownloadOut)
def create_download(body: DownloadIn, request: Request, event: MemberEvent, user: VerifiedUser, db: DB) -> DownloadOut:
    rate_limit.enforce(f"download:{user.id}", rate_limit.Limit(60, 600))
    s = get_settings()
    if len(body.photo_ids) > s.zip_max_photos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {s.zip_max_photos} photos per download")
    allowed = viewable_photos(db, event, user, body.photo_ids)
    if len(allowed) != len(set(body.photo_ids)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only download photos you matched or uploaded")
    token = downloads.create_token(user.id, event.id, [p.id for p in allowed])
    return DownloadOut(url=f"/api/downloads/{token}", expires_in=s.download_token_seconds, count=len(allowed))


def _iter_object(key: str) -> Iterator[bytes]:
    body, _ = storage.open_stream(key)
    try:
        yield from body.iter_chunks(chunk_size=256 * 1024)
    finally:
        body.close()


@router.get("/downloads/{token}")
def redeem_download(token: str, user: CurrentUser, db: DB) -> StreamingResponse:
    # Links are reusable for their short life (retries, resumed downloads) but not endlessly:
    # each redemption can stream a ZIP of up to ZIP_MAX_PHOTOS originals.
    rate_limit.enforce(f"download-redeem:{user.id}", rate_limit.Limit(120, 600))
    try:
        claim = downloads.read_token(token)
    except downloads.InvalidDownloadToken as e:
        raise HTTPException(status.HTTP_410_GONE, str(e)) from e
    # Bound to the user who requested it: a leaked link is useless to anyone else.
    if claim.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This download link belongs to another account")
    event = db.get(Event, claim.event_id)
    if event is None or not user.is_verified or not can_access(db, event, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this event")
    photos = viewable_photos(db, event, user, claim.photo_ids)
    if len(photos) != len(claim.photo_ids) or any(p.original_key is None for p in photos):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Some photos are no longer available to you")

    headers = {"Cache-Control": "private, no-store"}
    if not claim.as_zip:
        photo = photos[0]
        name = downloads.safe_filename(photo.original_filename, f"photo-{photo.id.hex[:8]}")
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return StreamingResponse(_iter_object(photo.original_key or ""), media_type="image/jpeg", headers=headers)

    zs = ZipStream(compress_type=ZIP_STORED, sized=False)  # JPEGs don't compress further
    used: set[str] = set()
    for i, photo in enumerate(photos, start=1):
        name = downloads.safe_filename(photo.original_filename, f"photo-{i:03d}")
        if name in used:
            name = f"{name[:-4]}-{i}.jpg"
        used.add(name)
        zs.add(_iter_object(photo.original_key or ""), name)
    headers["Content-Disposition"] = f'attachment; filename="{event.slug}-photos.zip"'
    return StreamingResponse(iter(zs), media_type="application/zip", headers=headers)
