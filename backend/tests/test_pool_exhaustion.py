"""SEC-042: when the DB connection pool is exhausted (a 60-way burst saturating the CPU made
even short auth queries wait past POOL timeout), requests must degrade to 503 + Retry-After
like every other overload path, never to a 500. The pool is also sized explicitly."""

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.api import deps
from app.core.config import get_settings
from app.core.db import CONNECT_ARGS, engine  # noqa: F401  (engine options under test)
from tests.conftest import new_client


def test_pool_exhaustion_is_a_503_not_a_500(monkeypatch: pytest.MonkeyPatch, make_user, login_as) -> None:  # type: ignore[no-untyped-def]
    c = login_as(make_user("pool@example.com"))

    def exhausted(*_a: object, **_k: object) -> bool:
        raise PoolTimeout("QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 10.00")

    monkeypatch.setattr(deps, "session_is_live", exhausted)
    r = c.get("/api/me")
    assert r.status_code == 503, r.text
    assert r.headers.get("retry-after", "").isdigit()
    assert "QueuePool" not in r.text  # no internals leaked


def test_pool_is_sized_from_settings() -> None:
    s = get_settings()
    assert engine.pool.size() == s.db_pool_size
    assert engine.pool._max_overflow == s.db_max_overflow  # no public accessor for overflow
    assert s.db_pool_size + s.db_max_overflow >= 30


def test_unrelated_endpoints_still_answer_normally() -> None:
    assert new_client().get("/api/health").status_code == 200
