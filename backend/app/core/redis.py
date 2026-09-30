from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


def redis_client(url: str) -> "Redis[str]":
    # Bounded: a hung Redis must fail requests fast instead of pinning every API thread.
    return Redis.from_url(
        url, decode_responses=True, socket_timeout=5, socket_connect_timeout=3, health_check_interval=30
    )


@lru_cache
def get_redis() -> "Redis[str]":
    return redis_client(get_settings().redis_url)
