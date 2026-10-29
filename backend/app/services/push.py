"""Apple push notifications (APNs, token-based auth over HTTP/2).

Payloads never carry personal data: no names, photos, counts, faces or event names. The
text is a localization key the app resolves on the device; the only data is what the app
needs to open the right screen (kind + ids). `payload()` builds every notification and
tests assert its exact key set.

Push is best-effort and off until APNS_KEY_P8/KEY_ID/TEAM_ID/TOPIC are configured.
Callers send after their transaction has committed (never while holding a connection).
"""

import contextlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Literal

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Device, EventMember, MemberRole, MemberStatus

log = logging.getLogger(__name__)

Kind = Literal["search_ready", "search_rejected", "moderation_pending", "new_photos"]
HOSTS = {"sandbox": "https://api.sandbox.push.apple.com", "production": "https://api.push.apple.com"}
# The only top-level keys a payload may have (tests enforce it).
PAYLOAD_KEYS = {"aps", "kind", "event_id", "search_id"}


@dataclass(frozen=True)
class Notice:
    kind: Kind
    event_id: uuid.UUID
    search_id: str | None = None


def payload(notice: Notice) -> dict[str, object]:
    body: dict[str, object] = {
        "aps": {
            "alert": {"title-loc-key": f"push.{notice.kind}.title", "loc-key": f"push.{notice.kind}.body"},
            "sound": "default",
        },
        "kind": notice.kind,
        "event_id": str(notice.event_id),
    }
    if notice.search_id:
        body["search_id"] = notice.search_id
    return body


def enabled() -> bool:
    s = get_settings()
    return bool(s.apns_key_p8 and s.apns_key_id and s.apns_team_id and s.apns_topic)


_lock = threading.Lock()
_jwt: tuple[str, float] | None = None
_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Route APNs requests through a fake (tests)."""
    global _transport, _jwt
    with _lock:
        _transport, _jwt = transport, None


def _provider_token() -> str:
    """ES256 JWT for APNs; Apple wants it reused for 20-60 min, not minted per request."""
    global _jwt  # noqa: PLW0603
    s = get_settings()
    with _lock:
        if _jwt is None or time.time() - _jwt[1] > 50 * 60:
            token = jwt.encode({"iss": s.apns_team_id, "iat": int(time.time())}, s.apns_key_p8, algorithm="ES256", headers={"kid": s.apns_key_id})
            _jwt = (token, time.time())
        return _jwt[0]


def _client() -> httpx.Client:
    s = get_settings()
    if _transport is not None:
        return httpx.Client(transport=_transport, base_url=HOSTS[s.apns_env], timeout=s.apns_timeout_seconds)
    return httpx.Client(http2=True, base_url=HOSTS[s.apns_env], timeout=s.apns_timeout_seconds)


def _send(client: httpx.Client, device_token: str, notice: Notice) -> bool:
    """True if APNs says the device token is dead (remove it)."""
    s = get_settings()
    try:
        r = client.post(
            f"/3/device/{device_token}",
            json=payload(notice),
            headers={
                "authorization": f"bearer {_provider_token()}",
                "apns-topic": s.apns_topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-expiration": str(int(time.time()) + 24 * 3600),
            },
        )
    except httpx.HTTPError:
        log.warning("APNs request failed")
        return False
    if r.status_code == 200:
        return False
    reason = ""
    with contextlib.suppress(ValueError):
        reason = r.json().get("reason", "")
    log.warning("APNs rejected a notification: %s %s", r.status_code, reason)
    return r.status_code == 410 or reason in {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}


def notify_users(user_ids: list[uuid.UUID], notice: Notice) -> int:
    """Send to every signed-in device of these users; returns how many were sent."""
    if not enabled() or not user_ids:
        return 0
    env = get_settings().apns_env
    with SessionLocal() as db:
        targets = [
            (d.id, d.apns_token)
            for d in db.scalars(
                select(Device).where(
                    Device.user_id.in_(user_ids), Device.revoked_at.is_(None), Device.apns_token.is_not(None), Device.apns_env == env
                )
            )
        ]
    if not targets:
        return 0
    dead: list[uuid.UUID] = []
    with _client() as client:
        for device_id, token in targets:
            if token and _send(client, token, notice):
                dead.append(device_id)
    if dead:
        with SessionLocal() as db:
            for d in db.scalars(select(Device).where(Device.id.in_(dead))):
                d.apns_token = None
            db.commit()
    return len(targets)


def organizers_of(db: Session, event_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(EventMember.user_id).where(
                EventMember.event_id == event_id,
                EventMember.role == MemberRole.organizer,
                EventMember.status == MemberStatus.approved,
            )
        )
    )


def notify_safely(user_ids: list[uuid.UUID], notice: Notice) -> None:
    """For background tasks: a push failure must never affect the request or job."""
    try:
        notify_users(user_ids, notice)
    except Exception:
        log.exception("Push notification failed")
