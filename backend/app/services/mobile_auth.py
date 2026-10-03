"""Mobile app sign-in: emailed 6-digit codes / magic links and device-bound sessions.

Codes live in Redis only (they are short-lived and single-use), stored as an HMAC keyed
with the server secret: a plain hash of a 6-digit code could be reversed by trying all
million values. A code dies after MOBILE_CODE_MAX_ATTEMPTS wrong guesses, and wrong guesses
also count toward an email+IP lockout like the web join code.

Sessions reuse the web session model (a refresh-token family in auth_tokens, ended by
logout, password reset and account deletion). What's added is the `devices` row that
owns the session and a P-256 public key from the device's Secure Enclave: every refresh
must be signed with it, so a refresh token copied off the device is useless.
"""

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_token, new_opaque_token, utcnow
from app.models import AuthToken, Device, TokenKind, User
from app.services import app_attest
from app.services.tokens import end_session, issue_refresh_token, rotate_refresh_token


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _code_mac(purpose: str, subject: str, code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{purpose}|{subject}|{code}".encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# --- Codes (sign-in and re-authentication) ------------------------------------------------


@dataclass(frozen=True)
class IssuedCode:
    code: str
    magic: str | None


def issue_code(purpose: str, subject: str, *, with_magic_link: bool) -> IssuedCode:
    """Replace any earlier code for (purpose, subject). `subject` is the email (sign-in)
    or the user id (re-authentication)."""
    s = get_settings()
    ttl = s.mobile_code_ttl_minutes * 60
    r = get_redis()
    key = f"mcode:{purpose}:{_email_key(subject)}"
    old = r.get(key)
    if old:
        old_magic = json.loads(old).get("m")
        if old_magic:
            r.delete(f"mmagic:{old_magic}")
    code = new_code()
    magic = new_opaque_token() if with_magic_link else None
    record = {"h": _code_mac(purpose, subject.strip().lower(), code), "m": hash_token(magic) if magic else None}
    pipe = r.pipeline()
    pipe.set(key, json.dumps(record), ex=ttl)
    pipe.delete(f"{key}:tries")
    if magic:
        pipe.set(f"mmagic:{hash_token(magic)}", subject.strip().lower(), ex=ttl)
    pipe.execute()
    return IssuedCode(code=code, magic=magic)


def check_code(purpose: str, subject: str, code: str) -> bool:
    """Single-use, constant-time check. Wrong guesses count; at the limit the code dies."""
    s = get_settings()
    r = get_redis()
    key = f"mcode:{purpose}:{_email_key(subject)}"
    tries = r.incr(f"{key}:tries")
    r.expire(f"{key}:tries", s.mobile_code_ttl_minutes * 60)
    raw = r.get(key)
    if raw is None:
        return False
    if tries > s.mobile_code_max_attempts:
        r.delete(key)
        return False
    record = json.loads(raw)
    if not (code.isdigit() and len(code) == 6) or not hmac.compare_digest(
        record["h"], _code_mac(purpose, subject.strip().lower(), code)
    ):
        return False
    # Only the request that deletes the record wins (two concurrent correct guesses: one).
    if not r.delete(key):
        return False
    if record.get("m"):
        r.delete(f"mmagic:{record['m']}")
    return True


def consume_magic(token: str) -> str | None:
    """The email a magic link was issued for (single-use; also kills the matching code)."""
    r = get_redis()
    email = r.getdel(f"mmagic:{hash_token(token)}")
    if email:
        r.delete(f"mcode:signin:{_email_key(email)}")
    return email


# --- Device keys --------------------------------------------------------------------------


class BadDeviceKey(ValueError):
    pass


def load_public_key(b64: str) -> ec.EllipticCurvePublicKey:
    """A P-256 public key as iOS exports it (X9.63 uncompressed point, base64)."""
    try:
        raw = base64.b64decode(b64, validate=True)
        if len(raw) != 65 or raw[0] != 4:
            raise ValueError("not an uncompressed P-256 point")
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as e:
        raise BadDeviceKey(str(e)) from e


def refresh_message(refresh_token: str, device_id: uuid.UUID, ts: int) -> bytes:
    """What the device signs to refresh: binds the token, the device and the time."""
    return f"eventfaces-refresh|{hashlib.sha256(refresh_token.encode()).hexdigest()}|{device_id}|{ts}".encode()


def verify_signature(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        key = load_public_key(public_key_b64)
        key.verify(base64.b64decode(signature_b64, validate=True), message, ec.ECDSA(hashes.SHA256()))
        return True
    except (BadDeviceKey, InvalidSignature, ValueError):
        return False


# --- Sessions -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MobileSession:
    access_token: str
    refresh_token: str
    device: Device
    user: User


def find_or_create_user(db: Session, email: str) -> User:
    """Possession of the inbox proves the address: new accounts start verified."""
    # Insert-if-absent atomically: two devices finishing sign-in for a new address at the
    # same moment must not hit the unique constraint.
    db.execute(
        pg_insert(User)
        .values(id=uuid.uuid4(), email=email, password_hash=None, email_verified_at=utcnow())
        .on_conflict_do_nothing(index_elements=["email"])
    )
    user = db.scalar(select(User).where(User.email == email).with_for_update())
    if user is None or user.deleted_at is not None:
        raise RefreshRejected  # a soft-deleted account can't be signed into
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    return user


def start_device_session(db: Session, user: User, *, name: str, platform: str, app_version: str, public_key: str) -> MobileSession:
    load_public_key(public_key)  # raises BadDeviceKey
    s = get_settings()
    session_id = uuid.uuid4()
    refresh = issue_refresh_token(db, user, timedelta(days=s.refresh_token_days), session_id)
    device = Device(
        user_id=user.id, session_id=session_id, name=name, platform=platform, app_version=app_version, public_key=public_key
    )
    db.add(device)
    db.flush()
    access = create_access_token(user.id, user.role.value, session_id, audience="mobile")
    return MobileSession(access_token=access, refresh_token=refresh, device=device, user=user)


def device_for_session(db: Session, session_id: uuid.UUID | None) -> Device | None:
    if session_id is None:
        return None
    return db.scalar(select(Device).where(Device.session_id == session_id))


def session_of(db: Session, refresh_token: str) -> uuid.UUID | None:
    """The session a refresh token belongs to (read-only; any state)."""
    return db.scalar(
        select(AuthToken.session_id).where(AuthToken.token_hash == hash_token(refresh_token), AuthToken.kind == TokenKind.refresh)
    )


class RefreshRejected(Exception):
    pass


def refresh_device_session(
    db: Session,
    refresh_token: str,
    device_id: uuid.UUID,
    ts: int,
    signature: str,
    app_version: str,
    *,
    assertion: str | None = None,
) -> MobileSession:
    s = get_settings()
    device = db.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None or device.revoked_at is not None:
        raise RefreshRejected
    now = int(utcnow().timestamp())
    if abs(now - ts) > s.mobile_signature_skew_seconds:
        raise RefreshRejected
    message = refresh_message(refresh_token, device_id, ts)
    if not verify_signature(device.public_key, message, signature):
        raise RefreshRejected
    # A signature is good once: a captured request can't be replayed inside the window.
    if not get_redis().set(f"msig:{hashlib.sha256(signature.encode()).hexdigest()}", "1", nx=True, ex=2 * s.mobile_signature_skew_seconds + 5):
        raise RefreshRejected
    # The token must belong to this device's session (no cross-session or web tokens).
    if session_of(db, refresh_token) != device.session_id:
        raise RefreshRejected
    token = rotate_refresh_token(db, refresh_token, timedelta(seconds=s.refresh_reuse_grace_seconds))
    if token is None:  # expired, or a replay that rotate_refresh_token answered by ending the session
        raise RefreshRejected
    user = db.get(User, token.user_id)
    if user is None or user.deleted_at is not None:
        raise RefreshRejected
    new_refresh = issue_refresh_token(db, user, timedelta(days=s.refresh_token_days), device.session_id)
    device.last_seen_at = utcnow()
    device.app_version = app_version
    if app_attest.enabled():
        app_attest.record_refresh_assertion(device, assertion, message)  # report-only
    access = create_access_token(user.id, user.role.value, device.session_id, audience="mobile")
    return MobileSession(access_token=access, refresh_token=new_refresh, device=device, user=user)


def revoke_device(db: Session, device: Device) -> None:
    """Sign the device out now: end its session (its access token dies with it) and
    forget its push token."""
    end_session(db, device.session_id)
    device.revoked_at = device.revoked_at or utcnow()
    device.apns_token = None
    device.apns_env = None


def revoke_user_devices(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(Device)
        .where(Device.user_id == user_id, Device.revoked_at.is_(None))
        .values(revoked_at=utcnow(), apns_token=None, apns_env=None)
    )
