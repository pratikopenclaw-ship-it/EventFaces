import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, ManagedEvent, SuperAdmin, VerifiedUser
from app.models import EventMember, MemberRole, MemberStatus, User, UserRole
from app.schemas.event import MemberOut, MemberUpdate, OrganizerAssign

router = APIRouter(prefix="/api/events/{event_id}", tags=["members"])


def _out(m: EventMember, email: str) -> MemberOut:
    return MemberOut(
        user_id=m.user_id,
        email=email,
        role=m.role,
        status=m.status,
        joined_at=m.joined_at,
        expires_at=m.expires_at,
    )


@router.get("/members", response_model=list[MemberOut])
def list_members(event: ManagedEvent, db: DB) -> list[MemberOut]:
    rows = db.execute(
        select(EventMember, User.email)
        .join(User, User.id == EventMember.user_id)
        .where(EventMember.event_id == event.id)
        .order_by(EventMember.role, EventMember.joined_at)
    ).all()
    return [_out(m, email) for m, email in rows]


@router.post("/organizers", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def assign_organizer(
    body: OrganizerAssign, event: ManagedEvent, admin: SuperAdmin, db: DB
) -> MemberOut:
    user = db.scalar(select(User).where(User.email == body.email, User.deleted_at.is_(None)))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that email; ask them to sign up first")
    if user.role == UserRole.attendee:
        user.role = UserRole.organizer
    m = db.get(EventMember, (event.id, user.id))
    if m is None:
        m = EventMember(event_id=event.id, user_id=user.id)
        db.add(m)
    m.role = MemberRole.organizer
    m.status = MemberStatus.approved
    m.expires_at = None
    db.commit()
    db.refresh(m)
    return _out(m, user.email)


def _get_editable_member(db: DB, event_id: uuid.UUID, user_id: uuid.UUID, actor: User) -> EventMember:
    m = db.get(EventMember, (event_id, user_id))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if m.role == MemberRole.organizer and actor.role != UserRole.super_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super admin can change organizers")
    return m


@router.patch("/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID, body: MemberUpdate, event: ManagedEvent, actor: VerifiedUser, db: DB
) -> MemberOut:
    m = _get_editable_member(db, event.id, user_id, actor)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("status") is not None:
        m.status = changes["status"]
    if "expires_at" in changes:
        m.expires_at = changes["expires_at"]
    db.commit()
    email = db.scalar(select(User.email).where(User.id == user_id))
    return _out(m, email or "")


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, event: ManagedEvent, actor: VerifiedUser, db: DB) -> None:
    m = _get_editable_member(db, event.id, user_id, actor)
    db.delete(m)
    db.commit()
