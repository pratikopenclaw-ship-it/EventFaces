"""One-time capture tokens: a camera search must present a fresh token issued to the
same user for the same event. Stored in Redis (hashed), consumed atomically with GETDEL.

A server can't prove pixels came from a live camera; the token ensures a search starts
from our guided capture flow within the last minute and can't be replayed or scripted
in bulk without going through it.
"""

import json
import uuid

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import hash_token, new_opaque_token


def issue(user_id: uuid.UUID, event_id: uuid.UUID) -> str:
    raw = new_opaque_token()
    get_redis().setex(
        f"captok:{hash_token(raw)}",
        get_settings().capture_token_seconds,
        json.dumps({"user": str(user_id), "event": str(event_id)}),
    )
    return raw


def consume(raw: str, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    """True if the token is valid for this user+event. Single use, even on mismatch."""
    value = get_redis().getdel(f"captok:{hash_token(raw)}")
    if value is None:
        return False
    try:
        data = json.loads(value)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("user") == str(user_id) and data.get("event") == str(event_id)
