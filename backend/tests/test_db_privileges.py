"""The app's database role is least-privilege, and the search audit log is append-only."""

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.security import utcnow
from app.models import SearchAudit


def test_app_connects_as_least_privilege_role() -> None:
    with engine.connect() as conn:
        role, superuser = conn.execute(text("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")).one()
    assert role == "eventfaces_app" and superuser is False


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE evil (id int)",
        "DROP TABLE photos",
        "ALTER TABLE users ADD COLUMN evil text",
        "TRUNCATE users CASCADE",
        "UPDATE alembic_version SET version_num = '0001'",
        "ALTER TABLE search_audit DISABLE TRIGGER search_audit_guard",
        "CREATE ROLE evil",
        "GRANT eventfaces_app TO PUBLIC",
    ],
)
def test_app_role_cannot_change_schema_or_privileges(statement: str) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)), engine.begin() as conn:
        conn.execute(text(statement))


def _audit(db: Session, days_old: int) -> SearchAudit:
    row = SearchAudit(user_id=None, event_id=None, match_count=3, created_at=utcnow() - timedelta(days=days_old))
    db.add(row)
    db.commit()
    return row


def test_audit_rows_cannot_be_rewritten(db: Session, make_user) -> None:
    user = make_user("audited@example.com")
    row = SearchAudit(user_id=user.id, event_id=None, match_count=3)
    db.add(row)
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE search_audit SET match_count = 0 WHERE id = :id"), {"id": row.id})
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE search_audit SET created_at = now() - interval '999 days' WHERE id = :id"), {"id": row.id})
    db.rollback()
    # Anonymization (as done on account/event deletion) is allowed
    db.execute(text("UPDATE search_audit SET user_id = NULL WHERE id = :id"), {"id": row.id})
    db.commit()


def test_recent_audit_rows_cannot_be_deleted(db: Session) -> None:
    recent = _audit(db, days_old=5)
    old = _audit(db, days_old=400)
    with pytest.raises(DBAPIError, match="younger than 30 days"):
        db.execute(text("DELETE FROM search_audit WHERE id = :id"), {"id": recent.id})
    db.rollback()
    db.execute(text("DELETE FROM search_audit WHERE id = :id"), {"id": old.id})  # retention-age: allowed
    db.commit()


def test_audit_retention_setting_respects_trigger_floor() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(audit_retention_days=7)  # type: ignore[call-arg]


def test_redis_requires_authentication() -> None:
    import os
    from urllib.parse import urlparse

    import redis

    url = urlparse(os.environ["REDIS_URL"])
    anonymous = redis.Redis(host=url.hostname, port=url.port or 6379, socket_timeout=3)
    with pytest.raises(redis.exceptions.AuthenticationError):
        anonymous.ping()
