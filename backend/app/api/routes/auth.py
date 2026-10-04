import uuid
from urllib.parse import quote
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.cookies import clear_auth_cookies, set_auth_cookies, set_csrf_cookie, set_theme_cookie
from app.api.deps import DB, CurrentUser
from app.core import rate_limit
from app.core.config import get_settings
from app.core.email import Mail, get_mailer
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    REFRESH_COOKIE,
    create_access_token,
    hash_password,
    utcnow,
    verify_password,
)
from app.models import TokenKind, User, UserRole
from app.schemas.auth import (
    EmailIn,
    LoginIn,
    MessageOut,
    PreferencesIn,
    ResetPasswordIn,
    SignupIn,
    TokenIn,
    UserOut,
)
from app.services import legal, mobile_auth
from app.services.tokens import (
    consume_token,
    end_session,
    find_valid_token,
    issue_refresh_token,
    issue_token,
    revoke_user_tokens,
    rotate_refresh_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_EMAIL_MSG = "If that address can receive email, a message is on its way."


def _send(background: BackgroundTasks, to: str, subject: str, body: str) -> None:
    background.add_task(get_mailer().send, Mail(to=to, subject=subject, body=body))


def _send_verification(db: DB, background: BackgroundTasks, user: User, next_path: str | None = None) -> None:
    s = get_settings()
    raw = issue_token(db, user, TokenKind.verify_email, timedelta(hours=s.verify_token_hours))
    link = f"{s.frontend_url}/verify-email?token={raw}"
    if next_path:  # validated by SignupIn (join pages only)
        link += f"&next={quote(next_path, safe='')}"
    _send(background, user.email, "Verify your EventFaces email", f"Confirm your email:\n\n{link}\n")


def start_session(db: DB, response: Response, user: User, session_id: uuid.UUID | None = None) -> None:
    """Issue cookies for a new login session, or for the next rotation of an existing one."""
    s = get_settings()
    session_id = session_id or uuid.uuid4()
    refresh = issue_refresh_token(db, user, timedelta(days=s.refresh_token_days), session_id)
    set_auth_cookies(response, create_access_token(user.id, user.role.value, session_id), refresh)
    set_theme_cookie(response, user.theme)  # a signed-in device follows the profile's theme


@router.get("/csrf")
def csrf(response: Response) -> dict[str, str]:
    return {"csrf_token": set_csrf_cookie(response)}


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED, response_model=MessageOut)
def signup(body: SignupIn, request: Request, db: DB, background: BackgroundTasks) -> MessageOut:
    rate_limit.enforce(f"signup:{rate_limit.client_ip(request)}", rate_limit.Limit(10, 3600))
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        # Same response either way so signup can't be used to discover accounts.
        _send(
            background,
            existing.email,
            "EventFaces sign-up attempt",
            "Someone tried to sign up with this address, but you already have an account. "
            "If you forgot your password, use 'Forgot password' on the login page.",
        )
    else:
        db.commit()  # no pooled connection held while hashing (SEC-041)
        password_hash = hash_password(body.password)
        user = User(email=body.email, password_hash=password_hash, role=UserRole.attendee)
        db.add(user)
        db.flush()
        legal.accept(db, user, "terms", locale=legal.locale_from(request.headers.get("accept-language")), channel="web")
        _send_verification(db, background, user, body.next)
    db.commit()
    return MessageOut(detail="Check your inbox to verify your email address.")


@router.post("/verify-email", response_model=UserOut)
def verify_email(body: TokenIn, db: DB) -> User:
    token = consume_token(db, body.token, TokenKind.verify_email)
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    user = db.get(User, token.user_id)
    if user is None or user.deleted_at is not None:
        # Not `assert`: asserts vanish under `python -O` and would turn this into a 500.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    db.commit()
    return user


@router.post("/resend-verification", response_model=MessageOut)
def resend_verification(
    body: EmailIn, request: Request, db: DB, background: BackgroundTasks
) -> MessageOut:
    rate_limit.enforce(f"resend:{rate_limit.client_ip(request)}", rate_limit.Limit(5, 3600))
    user = db.scalar(select(User).where(User.email == body.email, User.deleted_at.is_(None)))
    if user is not None and not user.is_verified:
        _send_verification(db, background, user)
        db.commit()
    return MessageOut(detail=GENERIC_EMAIL_MSG)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> User:
    limit = rate_limit.Limit.parse(get_settings().login_rate_limit)
    ip = rate_limit.client_ip(request)
    rate_limit.enforce(f"login:ip:{ip}", rate_limit.Limit(limit.count * 5, limit.seconds))
    rate_limit.enforce(f"login:{ip}:{body.email.lower()}", limit)

    user = db.scalar(select(User).where(User.email == body.email, User.deleted_at.is_(None)))
    db.commit()  # no pooled connection held while hashing (SEC-041)
    if user is None or user.password_hash is None:  # unknown, or a passwordless (app) account
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    start_session(db, response, user)
    db.commit()
    return user


@router.post("/refresh", response_model=UserOut)
def refresh(request: Request, response: Response, db: DB) -> User:
    raw = request.cookies.get(REFRESH_COOKIE)
    grace = timedelta(seconds=get_settings().refresh_reuse_grace_seconds)
    # An app session's refresh token only works with its device signature
    # (/api/mobile/auth/refresh): presented as a cookie, it is refused without rotating.
    if raw and mobile_auth.device_for_session(db, mobile_auth.session_of(db, raw)) is not None:
        raw = None
    token = rotate_refresh_token(db, raw, grace) if raw else None
    user = db.get(User, token.user_id) if token else None
    if token is None or user is None or user.deleted_at is not None:
        db.commit()  # keeps a replay-triggered session revocation
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    start_session(db, response, user, token.session_id)  # rotation within the same session
    db.commit()
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DB) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    token = consume_token(db, raw, TokenKind.refresh) if raw else None
    if token is not None and token.session_id is not None:
        end_session(db, token.session_id)  # the session's access tokens die with it
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_auth_cookies(response)
    return response


@router.post("/forgot-password", response_model=MessageOut)
def forgot_password(
    body: EmailIn, request: Request, db: DB, background: BackgroundTasks
) -> MessageOut:
    rate_limit.enforce(f"forgot:{rate_limit.client_ip(request)}", rate_limit.Limit(5, 3600))
    user = db.scalar(select(User).where(User.email == body.email, User.deleted_at.is_(None)))
    if user is not None:
        s = get_settings()
        raw = issue_token(db, user, TokenKind.reset_password, timedelta(minutes=s.reset_token_minutes))
        link = f"{s.frontend_url}/reset-password?token={raw}"
        _send(background, user.email, "Reset your EventFaces password", f"Reset link:\n\n{link}\n")
        db.commit()
    return MessageOut(detail=GENERIC_EMAIL_MSG)


@router.post("/reset-password", response_model=MessageOut)
def reset_password(body: ResetPasswordIn, db: DB) -> MessageOut:
    # Validate the link before paying for a hash, then hash with no connection or lock
    # held (SEC-041), then consume the token under its row lock.
    if find_valid_token(db, body.token, TokenKind.reset_password) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    db.rollback()
    password_hash = hash_password(body.password)
    token = consume_token(db, body.token, TokenKind.reset_password)
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    user = db.get(User, token.user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    user.password_hash = password_hash
    # Receiving the reset email proves control of the address.
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    revoke_user_tokens(db, user.id, TokenKind.refresh)  # log out all sessions, app ones too
    mobile_auth.revoke_user_devices(db, user.id)
    revoke_user_tokens(db, user.id, TokenKind.reset_password)
    db.commit()
    return MessageOut(detail="Password updated. Please log in.")


me_router = APIRouter(prefix="/api", tags=["me"])


@me_router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@me_router.patch("/me/preferences", response_model=UserOut)
def update_preferences(body: PreferencesIn, response: Response, user: CurrentUser, db: DB) -> User:
    user.theme = body.theme
    db.commit()
    set_theme_cookie(response, user.theme)
    return user
