import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, ManagedEvent, MemberEvent, VerifiedUser
from app.core import rate_limit
from app.core.security import utcnow
from app.models import Event, Photo, PhotoReport, PhotoStatus, ReportStatus, User
from app.schemas.community import ModerateIn, ModerationItem, ReportIn, ReportOut, ResolveReportIn
from app.services.photo_access import viewable_photo
from app.services.photo_pipeline import retire_photo

router = APIRouter(prefix="/api/events/{event_id}", tags=["moderation"])


def _locked_photo(db: DB, event: Event, photo_id: uuid.UUID) -> Photo:
    """Row-locked so it can't race with an in-flight indexing job (see index_photo)."""
    photo = db.get(Photo, photo_id, with_for_update=True)
    if photo is None or photo.event_id != event.id or photo.status == PhotoStatus.removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return photo


@router.get("/moderation", response_model=list[ModerationItem])
def moderation_queue(event: ManagedEvent, db: DB) -> list[ModerationItem]:
    rows = db.execute(
        select(Photo, User.email)
        .outerjoin(User, User.id == Photo.uploaded_by)
        .where(Photo.event_id == event.id, Photo.status == PhotoStatus.pending_review)
        .order_by(Photo.created_at)
    ).all()
    return [
        ModerationItem(
            id=p.id,
            original_filename=p.original_filename,
            uploader_email=email,
            index_status=p.index_status,
            face_count=p.face_count,
            created_at=p.created_at,
        )
        for p, email in rows
    ]


@router.post("/photos/{photo_id}/moderate", status_code=status.HTTP_204_NO_CONTENT)
def moderate(photo_id: uuid.UUID, body: ModerateIn, event: ManagedEvent, db: DB) -> None:
    photo = _locked_photo(db, event, photo_id)
    if photo.status != PhotoStatus.pending_review:
        raise HTTPException(status.HTTP_409_CONFLICT, "This photo isn't awaiting review")
    if body.action == "approve":
        photo.status = PhotoStatus.published
    else:
        retire_photo(db, photo, PhotoStatus.rejected)
    db.commit()


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: uuid.UUID, event: ManagedEvent, db: DB) -> None:
    """Admin delete: removes embeddings, grants and files; keeps a tombstone row."""
    photo = _locked_photo(db, event, photo_id)
    retire_photo(db, photo, PhotoStatus.removed)
    db.commit()


@router.post("/photos/{photo_id}/report", status_code=status.HTTP_201_CREATED)
def report_photo(photo_id: uuid.UUID, body: ReportIn, event: MemberEvent, user: VerifiedUser, db: DB) -> dict[str, str]:
    rate_limit.enforce(f"report:{user.id}", rate_limit.Limit(20, 3600))
    # You can only report photos you can see (matched, uploaded, or as an organizer).
    if viewable_photo(db, event, user, photo_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    existing = db.scalar(
        select(PhotoReport).where(
            PhotoReport.photo_id == photo_id,
            PhotoReport.reporter_id == user.id,
            PhotoReport.status == ReportStatus.open,
        )
    )
    if existing is None:
        db.add(PhotoReport(photo_id=photo_id, event_id=event.id, reporter_id=user.id, reason=body.reason, details=body.details))
        db.commit()
    return {"detail": "Thanks — the organizers will review this photo."}


@router.get("/reports", response_model=list[ReportOut])
def list_reports(event: ManagedEvent, db: DB, include_resolved: bool = False) -> list[ReportOut]:
    q = (
        select(PhotoReport, User.email)
        .outerjoin(User, User.id == PhotoReport.reporter_id)
        .where(PhotoReport.event_id == event.id)
        .order_by(PhotoReport.created_at.desc())
    )
    if not include_resolved:
        q = q.where(PhotoReport.status == ReportStatus.open)
    return [
        ReportOut(
            id=r.id,
            photo_id=r.photo_id,
            reason=r.reason,
            details=r.details,
            status=r.status,
            reporter_email=email,
            created_at=r.created_at,
        )
        for r, email in db.execute(q).all()
    ]


@router.post("/reports/{report_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
def resolve_report(report_id: uuid.UUID, body: ResolveReportIn, event: ManagedEvent, user: VerifiedUser, db: DB) -> None:
    report = db.get(PhotoReport, report_id)
    if report is None or report.event_id != event.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    now = utcnow()
    if body.action == "remove_photo":
        photo = db.get(Photo, report.photo_id, with_for_update=True)
        if photo is not None and photo.status != PhotoStatus.removed:
            retire_photo(db, photo, PhotoStatus.removed)
        # Close every open report on the same photo.
        for r in db.scalars(select(PhotoReport).where(PhotoReport.photo_id == report.photo_id, PhotoReport.status == ReportStatus.open)):
            r.status, r.resolved_at, r.resolved_by = ReportStatus.photo_removed, now, user.id
    else:
        report.status, report.resolved_at, report.resolved_by = ReportStatus.dismissed, now, user.id
    db.commit()
