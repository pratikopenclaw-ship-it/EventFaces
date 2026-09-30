"""SEC-032: every external dependency call is bounded in time, so a hung Redis, database,
storage or Google endpoint can't pin API threads forever."""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import redis

from app.core import storage
from app.core.db import engine
from app.core.redis import get_redis, redis_client


@pytest.fixture
def tarpit() -> Iterator[int]:
    """A local TCP server that accepts connections and never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except OSError:
                continue

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    yield server.getsockname()[1]
    stop.set()
    t.join()
    for s in held:
        s.close()
    server.close()


def test_redis_calls_time_out(tarpit: int) -> None:
    client = redis_client(f"redis://127.0.0.1:{tarpit}/0")
    t = time.monotonic()
    with pytest.raises(redis.exceptions.TimeoutError):
        client.ping()
    assert time.monotonic() - t < 10


def test_app_redis_client_has_timeouts() -> None:
    kwargs = get_redis().connection_pool.connection_kwargs
    assert 0 < kwargs["socket_timeout"] <= 5
    assert 0 < kwargs["socket_connect_timeout"] <= 5


def test_database_connect_and_pool_are_bounded() -> None:
    from app.core.db import CONNECT_ARGS

    assert engine.pool.timeout() <= 10
    assert 0 < CONNECT_ARGS["connect_timeout"] <= 10


def test_statement_timeout_applies_to_api_sessions() -> None:
    with engine.connect() as conn:
        value = conn.exec_driver_sql("SHOW statement_timeout").scalar()
    assert value not in ("0", None)
    with engine.connect() as conn, pytest.raises(Exception, match="statement timeout"):
        conn.exec_driver_sql("SET statement_timeout = '200ms'")
        conn.exec_driver_sql("SELECT pg_sleep(2)")


@pytest.mark.parametrize("client", [storage.get_s3, storage.get_public_s3])
def test_storage_client_timeouts(client) -> None:  # type: ignore[no-untyped-def]
    cfg = client()._client_config
    assert cfg.connect_timeout <= 5
    assert cfg.read_timeout <= 30
    assert cfg.retries["mode"] == "standard"
    assert cfg.retries.get("total_max_attempts", cfg.retries.get("max_attempts", 99)) <= 4  # 1 try + 3 retries


def test_google_client_timeout() -> None:
    from app.services.drive import google_http

    assert 0 < google_http().timeout <= 30
