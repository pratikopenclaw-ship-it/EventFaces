import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import hash_token, new_opaque_token, utcnow
from app.models import AuthToken, TokenKind, User


def issue_token(db: Session, user: User, kind: TokenKind, ttl: timedelta) -> str:
    """Create an opaque token, store its hash, and return the raw value (sent to the user)."""
    raw = new_opaque_token()
    db.add(
        AuthToken(
            user_id=user.id, kind=kind, token_hash=hash_token(raw), expires_at=utcnow() + ttl
        )
    )
    return raw


def consume_token(db: Session, raw: str, kind: TokenKind) -> AuthToken | None:
    """Mark a valid, unused, unexpired token as used and return it; None if invalid.

    The row is locked so two concurrent requests can't both use the same token.
    """
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == hash_token(raw), AuthToken.kind == kind)
        .with_for_update()
    )
    if token is None or token.used_at is not None or token.expires_at <= utcnow():
        return None
    token.used_at = utcnow()
    return token


def revoke_user_tokens(db: Session, user_id: uuid.UUID, kind: TokenKind) -> None:
    db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.kind == kind, AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )


def issue_refresh_token(db: Session, user: User, ttl: timedelta, session_id: uuid.UUID) -> str:
    raw = new_opaque_token()
    db.add(
        AuthToken(
            user_id=user.id,
            kind=TokenKind.refresh,
            token_hash=hash_token(raw),
            expires_at=utcnow() + ttl,
            session_id=session_id,
        )
    )
    return raw


def session_is_live(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
    """A session lives while it has an unused, unexpired refresh token."""
    return (
        db.scalar(
            select(AuthToken.id)
            .where(
                AuthToken.session_id == session_id,
                AuthToken.user_id == user_id,
                AuthToken.kind == TokenKind.refresh,
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > utcnow(),
            )
            .limit(1)
        )
        is not None
    )


def end_session(db: Session, session_id: uuid.UUID) -> None:
    db.execute(
        update(AuthToken)
        .where(AuthToken.session_id == session_id, AuthToken.kind == TokenKind.refresh, AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )


def rotate_refresh_token(db: Session, raw: str, grace: timedelta) -> AuthToken | None:
    """Consume a refresh token for rotation. Presenting one that was already rotated
    away (outside a short grace window for concurrent tabs) means it was copied, so the
    whole session is revoked: the thief and the victim must both log in again."""
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == hash_token(raw), AuthToken.kind == TokenKind.refresh)
        .with_for_update()
    )
    now = utcnow()
    if token is None or token.expires_at <= now:
        return None
    if token.used_at is not None:
        if token.session_id is not None and now - token.used_at > grace:
            end_session(db, token.session_id)
        return None
    token.used_at = now
    if token.session_id is None:  # issued before sessions existed
        token.session_id = uuid.uuid4()
    return token


def find_valid_token(db: Session, raw: str, kind: TokenKind) -> AuthToken | None:
    """Read-only validity check (no lock, not consumed): lets callers reject bad links
    before doing expensive work such as password hashing."""
    token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(raw), AuthToken.kind == kind))
    if token is None or token.used_at is not None or token.expires_at <= utcnow():
        return None
    return token
