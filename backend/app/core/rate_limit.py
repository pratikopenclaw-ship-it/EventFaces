"""Redis-backed fixed-window rate limiting and lockout counters."""

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.core.redis import get_redis


@dataclass(frozen=True)
class Limit:
    count: int
    seconds: int

    @classmethod
    def parse(cls, spec: str) -> "Limit":
        count, seconds = spec.split("/")
        return cls(int(count), int(seconds))


def client_ip(request: Request) -> str:
    """Client IP for rate limiting.

    X-Forwarded-For is client-controlled except for the entries appended by our own
    proxies, so we only trust the entry `trusted_proxy_hops` from the right. With 0
    (the default) the header is ignored and the TCP peer address is used.
    """
    hops = get_settings().trusted_proxy_hops
    forwarded = request.headers.get("x-forwarded-for")
    if hops > 0 and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def hit(key: str, limit: Limit) -> int:
    """Increment the counter for `key`; returns the current count in the window."""
    r = get_redis()
    full_key = f"rl:{key}"
    pipe = r.pipeline()
    pipe.incr(full_key)
    pipe.expire(full_key, limit.seconds, nx=True)
    count, _ = pipe.execute()
    return int(count)


def enforce(key: str, limit: Limit) -> None:
    if hit(key, limit) > limit.count:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, try again later")


# --- Lockouts (e.g. wrong access codes) ---


def is_locked(key: str, max_attempts: int) -> bool:
    value = get_redis().get(f"lock:{key}")
    return value is not None and int(value) >= max_attempts


def record_failure(key: str, window_seconds: int) -> int:
    r = get_redis()
    full_key = f"lock:{key}"
    pipe = r.pipeline()
    pipe.incr(full_key)
    pipe.expire(full_key, window_seconds)  # each failure extends the lock window
    count, _ = pipe.execute()
    return int(count)


def clear_failures(key: str) -> None:
    get_redis().delete(f"lock:{key}")
