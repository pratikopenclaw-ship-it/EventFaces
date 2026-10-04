"""Mobile app endpoints: passwordless sign-in, device-bound sessions, devices, push, config.

Everything here is bearer-authenticated (or pre-login) and sets no cookies. The event,
photo, search and privacy endpoints are shared with the web app unchanged: the same
dependencies, rules and limits apply whichever transport authenticated the user.
"""

import base64
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.api.app_version import VERSION_HEADER
from app.api.deps import DB, CurrentUser
from app.core import rate_limit
from app.core.config import get_settings
from app.core.email import Mail, get_mailer
from app.models import Device
from app.schemas.mobile import (
    AppConfigOut,
    AttestChallengeOut,
    AttestIn,
    AttestOut,
    CodeRequestIn,
    CodeVerifyIn,
    DeviceIn,
    DeviceOut,
    MagicLinkIn,
    MobileTokensOut,
    PushTokenIn,
    RefreshIn,
)
from app.schemas.auth import MessageOut, UserOut
from app.services import app_attest, legal, mobile_auth

router = APIRouter(prefix="/api/mobile/auth", tags=["mobile"])
me_router = APIRouter(prefix="/api", tags=["mobile"])

GENERIC_CODE_MSG = "If that address can receive email, a code is on its way."
INVALID_CODE = HTTPException(status.HTTP_400_BAD_REQUEST, "That code didn't work. Check it or request a new one.")
LOCKED = HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong codes. Try again in 15 minutes.")
SESSION_ENDED = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")


def _tokens(session: mobile_auth.MobileSession) -> MobileTokensOut:
    return MobileTokensOut(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=get_settings().access_token_minutes * 60,
        device_id=session.device.id,
        user=UserOut.model_validate(session.user),
    )


def _sign_in(db: DB, request: Request, email: str, device: DeviceIn) -> MobileTokensOut:
    try:
        user = mobile_auth.find_or_create_user(db, email)
    except mobile_auth.RefreshRejected:
        db.rollback()
        raise INVALID_CODE from None
    # The sign-in screen requires ticking "I accept the Terms and am at least 16" (the
    # schema enforces it); record it unless the current version is already on file.
    if not legal.has_current_terms(user):
        legal.accept(db, user, "terms", locale=legal.locale_from(request.headers.get("accept-language")), channel="ios")
    try:
        session = mobile_auth.start_device_session(
            db,
            user,
            name=device.name,
            platform=device.platform,
            app_version=request.headers.get(VERSION_HEADER, ""),
            public_key=device.public_key,
        )
    except mobile_auth.BadDeviceKey as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid device key") from e
    db.commit()
    return _tokens(session)


@router.post("/code/request", status_code=status.HTTP_202_ACCEPTED, response_model=MessageOut)
def request_code(body: CodeRequestIn, request: Request, background: BackgroundTasks) -> MessageOut:
    s = get_settings()
    limit = rate_limit.Limit.parse(s.mobile_code_request_rate_limit)
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"mcode-req:ip:{ip}", rate_limit.Limit(limit.count * 5, limit.seconds))
    rate_limit.enforce(f"mcode-req:{body.email.lower()}", limit)
    # Same answer and the same work whether or not the address has an account (no
    # enumeration): the account is created only when the code is used.
    issued = mobile_auth.issue_code("signin", body.email, with_magic_link=True)
    link = f"{s.frontend_url}/m/signin?t={issued.magic}"
    background.add_task(
        get_mailer().send,
        Mail(
            to=body.email,
            subject=f"{issued.code} is your EventFaces code",
            body=f"Your sign-in code: {issued.code}\n\nOr open this link on your phone to sign in:\n{link}\n\n"
            f"It expires in {s.mobile_code_ttl_minutes} minutes. If you didn't ask for it, you can ignore this email.\n",
        ),
    )
    return MessageOut(detail=GENERIC_CODE_MSG)


@router.post("/code/verify", response_model=MobileTokensOut)
def verify_code(body: CodeVerifyIn, request: Request, db: DB) -> MobileTokensOut:
    s = get_settings()
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"mcode-verify:ip:{ip}", rate_limit.Limit.parse(s.mobile_code_verify_rate_limit))
    lock_keys = [f"mcode:{body.email.lower()}", f"mcode-ip:{ip}"]
    if any(rate_limit.is_locked(k, s.join_lockout_attempts) for k in lock_keys):
        raise LOCKED
    if not mobile_auth.check_code("signin", body.email, body.code):
        for k in lock_keys:
            rate_limit.record_failure(k, s.join_lockout_seconds)
        raise INVALID_CODE
    rate_limit.clear_failures(lock_keys[0])
    return _sign_in(db, request, body.email, body.device)


@router.post("/magic", response_model=MobileTokensOut)
def magic_link(body: MagicLinkIn, request: Request, db: DB) -> MobileTokensOut:
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"mcode-verify:ip:{ip}", rate_limit.Limit.parse(get_settings().mobile_code_verify_rate_limit))
    email = mobile_auth.consume_magic(body.token)
    if email is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link has expired or was already used. Request a new code.")
    return _sign_in(db, request, email, body.device)


@router.post("/refresh", response_model=MobileTokensOut)
def refresh(body: RefreshIn, request: Request, db: DB) -> MobileTokensOut:
    rate_limit.enforce(f"mrefresh:{body.device_id}", rate_limit.Limit(30, 300))
    try:
        session = mobile_auth.refresh_device_session(
            db,
            body.refresh_token,
            body.device_id,
            body.ts,
            body.signature,
            request.headers.get(VERSION_HEADER, ""),
            assertion=body.assertion,
        )
    except mobile_auth.RefreshRejected:
        db.commit()  # keeps a replay-triggered session revocation
        raise SESSION_ENDED from None
    db.commit()
    return _tokens(session)


def _current_device(request: Request, db: DB) -> Device:
    """The device behind this request's bearer token (app requests only)."""
    if getattr(request.state, "transport", None) != "mobile":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only the app can do this")
    device = mobile_auth.device_for_session(db, request.state.session_id)
    if device is None or device.revoked_at is not None:
        raise SESSION_ENDED
    return device


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: CurrentUser, db: DB) -> Response:
    mobile_auth.revoke_device(db, _current_device(request, db))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("/me/devices", response_model=list[DeviceOut])
def list_devices(request: Request, user: CurrentUser, db: DB) -> list[DeviceOut]:
    current = getattr(request.state, "session_id", None)
    devices = db.scalars(
        select(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None)).order_by(Device.last_seen_at.desc())
    ).all()
    return [DeviceOut.model_validate(d).model_copy(update={"current": d.session_id == current}) for d in devices]


@me_router.delete("/me/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    device = db.scalar(select(Device).where(Device.id == device_id, Device.user_id == user.id).with_for_update())
    if device is None or device.revoked_at is not None:  # someone else's device looks the same as none
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    mobile_auth.revoke_device(db, device)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.put("/me/devices/current/push", status_code=status.HTTP_204_NO_CONTENT)
def register_push(body: PushTokenIn, request: Request, user: CurrentUser, db: DB) -> Response:
    device = _current_device(request, db)
    token = body.token.lower()
    # A push token identifies the install: if another account signed in on this phone
    # before, it must stop receiving this phone's notifications.
    db.execute(update(Device).where(Device.apns_token == token, Device.id != device.id).values(apns_token=None, apns_env=None))
    device.apns_token, device.apns_env = token, body.env
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.delete("/me/devices/current/push", status_code=status.HTTP_204_NO_CONTENT)
def unregister_push(request: Request, user: CurrentUser, db: DB) -> Response:
    device = _current_device(request, db)
    device.apns_token = device.apns_env = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


ATTEST_OFF = HTTPException(status.HTTP_404_NOT_FOUND, "App Attest is not enabled")


@me_router.post("/me/devices/current/attest/challenge", response_model=AttestChallengeOut)
def attest_challenge(request: Request, user: CurrentUser, db: DB) -> AttestChallengeOut:
    if not app_attest.enabled():
        raise ATTEST_OFF
    device = _current_device(request, db)
    rate_limit.enforce(f"attest:{device.id}", rate_limit.Limit(10, 3600))
    return AttestChallengeOut(challenge=base64.b64encode(app_attest.issue_challenge(device)).decode())


@me_router.post("/me/devices/current/attest", response_model=AttestOut)
def attest(body: AttestIn, request: Request, user: CurrentUser, db: DB) -> AttestOut:
    """Report-only: the result is recorded on the device; nothing is blocked either way."""
    if not app_attest.enabled():
        raise ATTEST_OFF
    device = db.scalar(select(Device).where(Device.id == _current_device(request, db).id).with_for_update())
    if device is None:  # removed since the session check
        raise SESSION_ENDED
    result = app_attest.record_attestation(db, device, body.key_id, body.attestation)
    db.commit()
    return AttestOut(status=result)


@me_router.get("/app/config", response_model=AppConfigOut)
def app_config(platform: Literal["ios"] = "ios") -> AppConfigOut:
    s = get_settings()
    return AppConfigOut(
        min_supported_version=s.ios_min_supported_version,
        latest_version=s.ios_latest_version,
        update_url=s.ios_update_url,
        app_attest=app_attest.enabled(),
    )
