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


def revoke_user_tokens(db: Session, user_id, kind: TokenKind) -> None:
    db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.kind == kind, AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
