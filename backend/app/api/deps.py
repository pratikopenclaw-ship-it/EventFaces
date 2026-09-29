import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ACCESS_COOKIE, decode_access_token
from app.models import Event, User, UserRole
from app.services import membership

DB = Annotated[Session, Depends(get_db)]

FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this event")


def get_current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    payload = decode_access_token(token) if token else None
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_verified_user(user: CurrentUser) -> User:
    if not user.is_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email address first")
    return user


VerifiedUser = Annotated[User, Depends(get_verified_user)]


def require_role(*roles: UserRole) -> Callable[[User], User]:
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return dependency


SuperAdmin = Annotated[User, Depends(require_role(UserRole.super_admin))]


def _load_event(db: Session, event_id: uuid.UUID, user: User) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        # Non-admins get 403 for unknown IDs too, so event IDs can't be probed.
        if user.role == UserRole.super_admin:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
        raise FORBIDDEN
    return event


def get_member_event(event_id: uuid.UUID, user: VerifiedUser, db: DB) -> Event:
    """Event-scoped dependency: approved, non-expired membership (or super_admin)."""
    event = _load_event(db, event_id, user)
    if not membership.can_access(db, event, user):
        raise FORBIDDEN
    return event


def get_managed_event(event_id: uuid.UUID, user: VerifiedUser, db: DB) -> Event:
    """Event-scoped dependency: organizer of this event (or super_admin)."""
    event = _load_event(db, event_id, user)
    if not membership.can_manage(db, event, user):
        raise FORBIDDEN
    return event


MemberEvent = Annotated[Event, Depends(get_member_event)]
ManagedEvent = Annotated[Event, Depends(get_managed_event)]
