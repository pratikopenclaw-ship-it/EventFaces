from collections.abc import Iterator
from typing import Any, cast

from sqlalchemy import CursorResult, Result, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


# Bounded waits: connecting, checking out a pooled connection, and any single statement.
CONNECT_ARGS: dict[str, Any] = {
    "connect_timeout": 5,
    "options": f"-c statement_timeout={get_settings().db_statement_timeout_ms}",
}
engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_timeout=10, connect_args=CONNECT_ARGS)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def affected(result: Result[Any]) -> int:
    """Rows affected by an INSERT/UPDATE/DELETE executed via Session.execute()."""
    return cast(CursorResult[Any], result).rowcount or 0
