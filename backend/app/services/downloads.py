"""Short-lived, signed download tokens bound to one user, one event and specific photos.

Tokens are JWTs signed with DOWNLOAD_TOKEN_SECRET (separate from the auth secret). A
single-photo token carries the photo ID; a ZIP token carries a random ticket whose
photo list lives in Redis (keeps URLs short). Authorization is re-checked when the
token is redeemed, so revoking membership takes effect immediately.
"""

import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import jwt

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import utcnow

AUDIENCE = "eventfaces-download"


@dataclass(frozen=True)
class DownloadClaim:
    user_id: uuid.UUID
    event_id: uuid.UUID
    photo_ids: list[uuid.UUID]
    as_zip: bool


class InvalidDownloadToken(Exception):
    pass


def create_token(user_id: uuid.UUID, event_id: uuid.UUID, photo_ids: list[uuid.UUID]) -> str:
    s = get_settings()
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "eid": str(event_id),
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=s.download_token_seconds),
    }
    if len(photo_ids) == 1:
        payload["pid"] = str(photo_ids[0])
    else:
        ticket = secrets.token_urlsafe(16)
        get_redis().setex(
            f"dl:{ticket}", s.download_token_seconds, json.dumps([str(p) for p in photo_ids])
        )
        payload["zip"] = ticket
    return jwt.encode(payload, s.download_token_secret, algorithm="HS256")


def read_token(token: str) -> DownloadClaim:
    try:
        payload = jwt.decode(
            token, get_settings().download_token_secret, algorithms=["HS256"], audience=AUDIENCE
        )
        user_id, event_id = uuid.UUID(payload["sub"]), uuid.UUID(payload["eid"])
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise InvalidDownloadToken("Download link is invalid or has expired") from e

    if "pid" in payload:
        return DownloadClaim(user_id, event_id, [uuid.UUID(payload["pid"])], as_zip=False)
    raw = get_redis().get(f"dl:{payload.get('zip')}")
    if raw is None:
        raise InvalidDownloadToken("Download link is invalid or has expired")
    return DownloadClaim(user_id, event_id, [uuid.UUID(p) for p in json.loads(raw)], as_zip=True)


def safe_filename(name: str | None, fallback: str) -> str:
    """ASCII-only, path-free file name ending in .jpg (we always serve re-encoded JPEGs)."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name or "")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80]
    return f"{stem or fallback}.jpg"
