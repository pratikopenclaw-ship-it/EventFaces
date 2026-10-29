"""Authorization matrix: every API operation × every role × both transports.

Roles: anonymous, unverified, attendee-not-member, attendee-member, revoked, expired,
organizer-of-other-event, organizer-of-this-event, super_admin.

Each operation has an access class (the intended policy). Allowed roles must not get
401/403 (a business outcome such as 404/409/410/422 is fine); denied roles must get
exactly 401 (anonymous) or 403. No cell may produce a 5xx. The operation list is checked
against the live OpenAPI schema, so a new endpoint without a matrix entry fails the suite.

Transports: "cookie" (the web app) and "bearer" (the iOS app: Authorization header from a
device session, X-App-Version, no CSRF cookie). Every cell must come out the same over
both, which is what "the app is never a weaker path into the system" means here.
"""

import base64
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password, hash_token, utcnow
from app.main import app
from app.models import (
    Event,
    EventMember,
    IndexStatus,
    Invite,
    JoinMode,
    MemberRole,
    MemberStatus,
    Photo,
    PhotoReport,
    PhotoSource,
    PhotoStatus,
    RemovalRequest,
    RemovalStatus,
    SearchGrant,
    User,
    UserRole,
)
from app.services import mobile_auth
from app.services.events import generate_access_code
from app.services.search import FACE_CONSENT_VERSION
from app.services import legal
from tests.conftest import PASSWORD, new_client
from tests.helpers import solid_jpeg

ROLES = [
    "anonymous",
    "unverified",
    "attendee_not_member",
    "attendee_member",
    "revoked",
    "expired",
    "organizer_other",
    "organizer_this",
    "super_admin",
]

# Who may call each access class (beyond these, the expected result is 401/403).
ALLOWED: dict[str, set[str]] = {
    "PUBLIC": set(ROLES),
    "AUTH": set(ROLES) - {"anonymous"},
    "VERIFIED": set(ROLES) - {"anonymous", "unverified"},
    "ORGANIZER": {"organizer_other", "organizer_this", "super_admin"},
    "MEMBER": {"attendee_member", "organizer_this", "super_admin"},
    "MANAGER": {"organizer_this", "super_admin"},
    "SUPER": {"super_admin"},
    # Needs a session (refresh cookie) but not a valid access token.
    "SESSION": set(ROLES) - {"anonymous"},
    # Credentials travel in the body (device-signed refresh): a session doesn't help, every
    # caller with bad credentials gets exactly 401.
    "CREDENTIAL": set(),
}
TRANSPORTS = ["cookie", "bearer"]
DEVICE_KEY = base64.b64encode(
    ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
).decode()

_PW_HASH = hash_password(PASSWORD)  # computed once: keeps 600+ cases fast


@dataclass
class World:
    event_a: Event
    event_b: Event
    users: dict[str, User]
    photo_a: Photo
    invite_a: Invite
    report_a: PhotoReport
    removal_a: RemovalRequest
    ids: dict[str, str] = field(default_factory=dict)


@pytest.fixture
def world(db: Session) -> World:
    now = utcnow()

    def user(name: str, role: UserRole = UserRole.attendee, verified: bool = True) -> User:
        u = User(
            email=f"{name}@example.com",
            password_hash=_PW_HASH,
            role=role,
            email_verified_at=now if verified else None,
            face_consent_at=now,
            face_consent_version=FACE_CONSENT_VERSION,
            terms_version=legal.VERSIONS["terms"],  # established users (the gates: test_legal.py)
            organizer_terms_version=legal.VERSIONS["organizer-terms"],
        )
        db.add(u)
        return u

    def event(name: str) -> Event:
        e = Event(
            name=name,
            slug=f"{name}-{uuid.uuid4().hex[:6]}",
            access_code=generate_access_code(),
            join_mode=JoinMode.code,
            guest_upload_enabled=True,
            drive_folder_id="1MatrixFolderXXXXXXX",
            allow_selfie_file_upload=True,
        )
        db.add(e)
        return e

    a, b = event("alpha"), event("beta")
    users = {
        "unverified": user("unverified", verified=False),
        "attendee_not_member": user("outsider"),
        "attendee_member": user("member"),
        "revoked": user("revoked"),
        "expired": user("expired"),
        "organizer_other": user("org-other", UserRole.organizer),
        "organizer_this": user("org-this", UserRole.organizer),
        "super_admin": user("admin", UserRole.super_admin),
    }
    db.flush()
    members = [
        (a, "unverified", MemberRole.attendee, MemberStatus.approved, None),
        (a, "attendee_member", MemberRole.attendee, MemberStatus.approved, None),
        (a, "revoked", MemberRole.attendee, MemberStatus.revoked, None),
        (a, "expired", MemberRole.attendee, MemberStatus.approved, now - timedelta(minutes=1)),
        (a, "organizer_this", MemberRole.organizer, MemberStatus.approved, None),
        (b, "organizer_other", MemberRole.organizer, MemberStatus.approved, None),
    ]
    for ev, name, role, st, exp in members:
        db.add(EventMember(event_id=ev.id, user_id=users[name].id, role=role, status=st, expires_at=exp))

    photo = Photo(
        id=uuid.uuid4(),
        event_id=a.id,
        source=PhotoSource.drive,
        drive_file_id="matrix-file",
        original_filename="p.jpg",
        status=PhotoStatus.published,
        index_status=IndexStatus.indexed,
    )
    for variant in ("original", "preview", "thumb"):
        key = storage.photo_key(a.id, photo.id, variant)
        storage.put_jpeg(key, solid_jpeg())
        setattr(photo, f"{variant}_key", key)
    db.add(photo)
    invite = Invite(event_id=a.id, email="invitee@example.com", token_hash=hash_token("inv-" + uuid.uuid4().hex), expires_at=now + timedelta(days=5))
    db.add(invite)
    db.flush()
    report = PhotoReport(photo_id=photo.id, event_id=a.id, reporter_id=users["attendee_member"].id, reason="other")
    removal = RemovalRequest(event_id=a.id, email="bystander@example.com", token_hash=hash_token("rm-" + uuid.uuid4().hex), status=RemovalStatus.submitted, matched_photo_ids=[photo.id])
    # The member matched the photo, so download/feedback exercise authorization, not "no match".
    grant = SearchGrant(
        user_id=users["attendee_member"].id, photo_id=photo.id, event_id=a.id, similarity=0.9, expires_at=now + timedelta(days=1)
    )
    db.add_all([report, removal, grant])
    db.commit()
    return World(a, b, users, photo, invite, report, removal)


@dataclass(frozen=True)
class Op:
    method: str
    path: str
    access: str
    json: Any = None
    content: bytes | None = None
    headers: dict[str, str] | None = None
    transports: tuple[str, ...] = ("cookie", "bearer")


E = "{event_a}"
OPS: list[Op] = [
    # --- public ---
    Op("GET", "/api/health", "PUBLIC"),
    Op("GET", "/api/auth/csrf", "PUBLIC"),
    Op("POST", "/api/auth/signup", "PUBLIC", json={"accept_terms": True, "email": "new-person@example.com", "password": PASSWORD}),
    Op("POST", "/api/auth/login", "PUBLIC", json={"email": "member@example.com", "password": PASSWORD}),
    Op("POST", "/api/auth/logout", "PUBLIC"),
    Op("POST", "/api/auth/refresh", "SESSION", transports=("cookie",)),
    Op("POST", "/api/auth/verify-email", "PUBLIC", json={"token": "not-a-real-token-123"}),
    Op("POST", "/api/auth/resend-verification", "PUBLIC", json={"email": "someone@example.com"}),
    Op("POST", "/api/auth/forgot-password", "PUBLIC", json={"email": "someone@example.com"}),
    Op("POST", "/api/auth/reset-password", "PUBLIC", json={"token": "not-a-real-token-123", "password": PASSWORD}),
    Op("GET", "/api/invites/not-a-real-token-123", "PUBLIC"),
    Op("POST", "/api/invites/register", "PUBLIC", json={"accept_terms": True, "token": "not-a-real-token-123", "password": PASSWORD}),
    Op("POST", "/api/removal-requests", "PUBLIC", json={"event": "{slug_a}", "email": "b@example.com"}),
    Op("GET", "/api/removal-requests/event/{slug_a}", "PUBLIC"),
    Op("GET", "/api/removal-requests/not-a-real-token-123", "PUBLIC"),
    Op("POST", "/api/removal-requests/not-a-real-token-123/submit", "PUBLIC"),
    Op("GET", "/api/app/config", "PUBLIC"),
    # --- the app's pre-login endpoints (bearer transport only: they're app requests) ---
    Op("POST", "/api/mobile/auth/code/request", "PUBLIC", json={"email": "phone@example.com"}, transports=("bearer",)),
    Op("POST", "/api/mobile/auth/code/verify", "PUBLIC", json={"accept_terms": True, "email": "phone@example.com", "code": "000000", "device": {"name": "Phone", "public_key": "{device_key}"}}, transports=("bearer",)),
    Op("POST", "/api/mobile/auth/magic", "PUBLIC", json={"accept_terms": True, "token": "not-a-real-token-1234567", "device": {"name": "Phone", "public_key": "{device_key}"}}, transports=("bearer",)),
    Op("POST", "/api/mobile/auth/refresh", "CREDENTIAL", json={"refresh_token": "not-a-real-token-1234567", "device_id": "{random_id}", "ts": 1, "signature": "AAAAAAAAAAAA"}, transports=("bearer",)),
    Op("GET", "/api/legal/terms", "PUBLIC"),
    # --- any logged-in user ---
    Op("GET", "/api/me", "AUTH"),
    Op("POST", "/api/me/legal/accept", "AUTH", json={"document": "terms", "version": "{terms_version}"}),
    Op("DELETE", "/api/me", "AUTH", json={"password": PASSWORD}),
    Op("GET", "/api/me/face-consent", "AUTH"),
    Op("DELETE", "/api/me/face-consent", "AUTH"),
    Op("PATCH", "/api/me/preferences", "AUTH", json={"theme": "dark"}),
    Op("POST", "/api/me/reauth-code", "AUTH"),
    Op("GET", "/api/me/devices", "AUTH"),
    Op("DELETE", "/api/me/devices/{random_id}", "AUTH"),
    Op("PUT", "/api/me/devices/current/push", "AUTH", json={"token": "ab" * 32, "env": "sandbox"}),
    Op("DELETE", "/api/me/devices/current/push", "AUTH"),
    Op("POST", "/api/me/devices/current/attest/challenge", "AUTH"),
    Op("POST", "/api/me/devices/current/attest", "AUTH", json={"key_id": "A" * 43 + "=", "attestation": "AAAAAAAA"}),
    Op("POST", "/api/mobile/auth/logout", "AUTH", transports=("bearer",)),
    Op("GET", "/api/selfie-requirements", "AUTH"),
    Op("POST", "/api/invites/accept", "AUTH", json={"token": "not-a-real-token-123"}),
    Op("GET", "/api/downloads/not-a-real-token", "AUTH"),
    # --- verified users ---
    Op("POST", "/api/me/face-consent", "VERIFIED", json={"version": FACE_CONSENT_VERSION}),
    Op("GET", "/api/events", "VERIFIED"),
    Op("GET", "/api/join/{slug_a}", "VERIFIED"),
    Op("POST", "/api/join", "VERIFIED", json={"slug": "{slug_a}", "code": "WRONGCODE"}),
    Op("POST", "/api/join/by-code", "VERIFIED", json={"code": "WRONGCODE"}),
    # --- billing (the fake provider's hosted checkout + webhook) ---
    Op("POST", "/api/contact", "PUBLIC", json={"name": "Matrix", "email": "matrix@example.com", "topic": "other", "message": "Hello from the matrix test"}),
    Op("GET", "/api/billing/plans", "PUBLIC"),
    # Server to server, authenticated only by its signature: every caller without a valid one gets 400.
    Op("POST", "/api/billing/webhook/fake", "PUBLIC", content=b'{"id":"evt_x"}', headers={"content-type": "application/json", "fake-signature": "t=1,v1=00"}),
    Op("POST", "/api/billing/checkout", "VERIFIED", json={"plan": "event_s", "event_name": "Matrix party"}),
    Op("GET", "/api/billing/test-checkout/fcs_not-a-session", "VERIFIED"),
    Op("POST", "/api/billing/test-checkout/fcs_not-a-session/pay", "VERIFIED", json={"card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvc": "123"}),
    Op("GET", "/api/billing/overview", "VERIFIED"),
    Op("GET", "/api/billing/orders/{random_id}", "VERIFIED"),
    Op("POST", "/api/billing/subscription/cancel", "VERIFIED"),
    Op("POST", "/api/billing/subscription/events", "VERIFIED", json={"name": "Matrix party"}),
    Op("GET", "/api/billing/addon-checkout/fcs_not-a-session", "VERIFIED"),
    Op("POST", "/api/billing/addon-checkout/fcs_not-a-session/pay", "VERIFIED", json={"card_number": "4242 4242 4242 4242", "expiry": "12/30", "cvc": "123"}),
    Op("GET", "/api/drive/service-account", "ORGANIZER"),
    # --- members of event A ---
    Op("GET", f"/api/events/{E}", "MEMBER"),
    Op("GET", f"/api/events/{E}/logo", "MEMBER"),
    Op("GET", f"/api/events/{E}/photo-alerts", "MEMBER"),
    Op("PUT", f"/api/events/{E}/photo-alerts", "MEMBER", json={"enabled": False}),
    Op("POST", f"/api/events/{E}/capture-token", "MEMBER"),
    Op("POST", f"/api/events/{E}/search?source=upload", "MEMBER", content=b"x", headers={"content-type": "image/jpeg"}),
    Op("GET", f"/api/events/{E}/my-photos", "MEMBER"),
    Op("GET", f"/api/events/{E}/shared-photos", "MEMBER"),
    Op("GET", f"/api/events/{E}/search-status", "MEMBER"),
    Op("GET", f"/api/events/{E}/my-uploads", "MEMBER"),
    Op("POST", f"/api/events/{E}/downloads", "MEMBER", json={"photo_ids": ["{photo_a}"]}),
    Op("POST", f"/api/events/{E}/feedback", "MEMBER", json={"photo_id": "{photo_a}", "verdict": "me"}),
    Op("POST", f"/api/events/{E}/feedback/missing", "MEMBER"),
    Op("POST", f"/api/events/{E}/photos/{{photo_a}}/report", "MEMBER", json={"reason": "other"}),
    Op("GET", f"/api/events/{E}/photos/{{photo_a}}/thumb", "MEMBER"),
    Op("POST", f"/api/events/{E}/uploads", "MEMBER", json={"filename": "a.jpg", "content_type": "image/jpeg", "size": 100}),
    Op("POST", f"/api/events/{E}/uploads/{{random_id}}/complete", "MEMBER"),
    Op("GET", f"/api/events/{E}/videos", "MEMBER"),
    Op("GET", f"/api/events/{E}/shortlist", "MEMBER"),
    Op("POST", f"/api/events/{E}/photos/{{photo_a}}/shortlist", "MEMBER"),
    Op("DELETE", f"/api/events/{E}/photos/{{photo_a}}/shortlist", "MEMBER"),
    Op("POST", f"/api/events/{E}/addons/checkout", "MEMBER", json={"kind": "human_edit", "photo_ids": ["{photo_a}"]}),
    # --- organizers of event A (and super admin) ---
    Op("GET", f"/api/events/{E}/admin", "MANAGER"),
    Op("GET", f"/api/events/{E}/usage", "MANAGER"),
    Op("PATCH", f"/api/events/{E}", "MANAGER", json={"description": "x"}),
    Op("PUT", f"/api/events/{E}/logo", "MANAGER", content=b"not an image", headers={"content-type": "image/png"}),
    Op("DELETE", f"/api/events/{E}/logo", "MANAGER"),
    Op("POST", f"/api/events/{E}/access-code/rotate", "MANAGER"),
    Op("GET", f"/api/events/{E}/members", "MANAGER"),
    Op("PATCH", f"/api/events/{E}/members/{{member_a}}", "MANAGER", json={"expires_at": None}),
    Op("DELETE", f"/api/events/{E}/members/{{member_a}}", "MANAGER"),
    Op("GET", f"/api/events/{E}/invites", "MANAGER"),
    Op("POST", f"/api/events/{E}/invites", "MANAGER", json={"csv": "x@example.com"}),
    Op("POST", f"/api/events/{E}/invites/{{invite_a}}/resend", "MANAGER"),
    Op("DELETE", f"/api/events/{E}/invites/{{invite_a}}", "MANAGER"),
    Op("GET", f"/api/events/{E}/qr", "MANAGER"),
    Op("GET", f"/api/events/{E}/sync", "MANAGER"),
    Op("POST", f"/api/events/{E}/sync", "MANAGER"),
    Op("GET", f"/api/events/{E}/photos", "MANAGER"),
    Op("POST", f"/api/events/{E}/photos/share", "MANAGER", json={"photo_ids": ["{photo_a}"], "shared": True}),
    Op("POST", f"/api/events/{E}/photos/share-faceless", "MANAGER", json={"confirm_no_people": True}),
    Op("DELETE", f"/api/events/{E}/photos/{{photo_a}}", "MANAGER"),
    Op("POST", f"/api/events/{E}/photos/{{photo_a}}/moderate", "MANAGER", json={"action": "approve"}),
    Op("POST", f"/api/events/{E}/videos", "MANAGER", json={"title": "Highlights", "url": "https://youtu.be/dQw4w9WgXcQ"}),
    Op("DELETE", f"/api/events/{E}/videos/{{random_id}}", "MANAGER"),
    Op("GET", f"/api/events/{E}/moderation", "MANAGER"),
    Op("GET", f"/api/events/{E}/reports", "MANAGER"),
    Op("POST", f"/api/events/{E}/reports/{{report_a}}/resolve", "MANAGER", json={"action": "dismiss"}),
    Op("GET", f"/api/events/{E}/removal-requests", "MANAGER"),
    Op("POST", f"/api/events/{E}/removal-requests/{{removal_a}}/resolve", "MANAGER", json={"action": "decline"}),
    Op("GET", f"/api/events/{E}/search-log", "MANAGER"),
    Op("GET", f"/api/events/{E}/match-quality", "MANAGER"),
    # --- super admin only ---
    Op("POST", "/api/events", "SUPER", json={"name": "New"}),
    Op("DELETE", f"/api/events/{E}", "SUPER"),
    Op("POST", f"/api/events/{E}/organizers", "SUPER", json={"email": "outsider@example.com"}),
    Op("GET", "/api/admin/match-quality", "SUPER"),
]


def _fill(template: Any, w: World) -> Any:
    values = {
        "event_a": str(w.event_a.id),
        "slug_a": w.event_a.slug,
        "photo_a": str(w.photo_a.id),
        "invite_a": str(w.invite_a.id),
        "report_a": str(w.report_a.id),
        "removal_a": str(w.removal_a.id),
        "member_a": str(w.users["attendee_member"].id),
        "random_id": str(uuid.uuid4()),
        "device_key": DEVICE_KEY,
        "terms_version": legal.VERSIONS["terms"],
    }
    if isinstance(template, str):
        for k, v in values.items():
            template = template.replace("{" + k + "}", v)
        return template
    if isinstance(template, dict):
        return {k: _fill(v, w) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, w) for v in template]
    return template


def _client(role: str, w: World, transport: str = "cookie") -> TestClient:
    if transport == "bearer":
        # What the app sends: a device session's bearer token and its version, no cookies.
        c = TestClient(app)
        c.headers["X-App-Version"] = "1.0.0"
        if role != "anonymous":
            with SessionLocal() as db:
                session = mobile_auth.start_device_session(
                    db, db.get(User, w.users[role].id), name="Matrix", platform="ios", app_version="1.0.0", public_key=DEVICE_KEY
                )
                db.commit()
            c.headers["Authorization"] = f"Bearer {session.access_token}"
        return c
    c = new_client()
    if role != "anonymous":
        r = c.post("/api/auth/login", json={"email": w.users[role].email, "password": PASSWORD})
        assert r.status_code == 200, r.text
    return c


def _schema_operations() -> set[tuple[str, str]]:
    return {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}


def _normalise(path: str) -> str:
    """Matrix path → OpenAPI path template (for the coverage check)."""
    import re

    path = path.split("?")[0]
    replacements = [
        (r"/api/me/devices/\{random_id\}", "/api/me/devices/{device_id}"),
        (r"/api/billing/orders/\{random_id\}", "/api/billing/orders/{order_id}"),
        (r"^/api/legal/(terms|organizer-terms|privacy|imprint)$", "/api/legal/{document}"),
        (r"/api/events/\{event_a\}", "/api/events/{event_id}"),
        (r"/api/events/\{event_id\}/videos/\{random_id\}", "/api/events/{event_id}/videos/{video_id}"),
        (r"\{photo_a\}", "{photo_id}"),
        (r"\{random_id\}", "{photo_id}"),
        (r"\{invite_a\}", "{invite_id}"),
        (r"\{report_a\}", "{report_id}"),
        (r"\{removal_a\}", "{request_id}"),
        (r"\{member_a\}", "{user_id}"),
        (r"/api/join/\{slug_a\}", "/api/join/{slug}"),
        (r"/api/removal-requests/event/\{slug_a\}", "/api/removal-requests/event/{slug}"),
        (r"/api/invites/not-a-real-token-123", "/api/invites/{token}"),
        (r"/api/removal-requests/not-a-real-token-123", "/api/removal-requests/{token}"),
        (r"/api/downloads/not-a-real-token", "/api/downloads/{token}"),
        (r"/photos/\{photo_id\}/thumb", "/photos/{photo_id}/{variant}"),
        (r"/api/billing/test-checkout/fcs_not-a-session", "/api/billing/test-checkout/{session_ref}"),
        (r"/api/billing/addon-checkout/fcs_not-a-session", "/api/billing/addon-checkout/{session_ref}"),
    ]
    for pattern, repl in replacements:
        path = re.sub(pattern, repl, path)
    return path


def test_matrix_covers_every_api_operation() -> None:
    covered = {(op.method, _normalise(op.path)) for op in OPS}
    missing = _schema_operations() - covered
    assert not missing, f"operations without an authorization-matrix entry: {sorted(missing)}"


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("op", OPS, ids=lambda o: f"{o.method} {o.path}")
def test_authorization_matrix(op: Op, role: str, transport: str, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    if transport not in op.transports:
        pytest.skip(f"{op.path} is not used over {transport}")
    if transport == "bearer" and role == "anonymous" and op.transports != ("bearer",):
        pytest.skip("an app without a session is an anonymous client: the cookie column covers it")
    # File selfies are allowed globally and for event A, so search cells test membership, not the camera rule.
    monkeypatch.setattr(get_settings(), "allow_selfie_file_upload", True)
    # App Attest on, so its cells exercise the endpoints rather than the "off" 404.
    monkeypatch.setattr(get_settings(), "app_attest_app_id", "ABCDE12345.app.eventfaces.ios")
    c = _client(role, world, transport)
    headers = dict(op.headers or {})
    r = c.request(
        op.method,
        _fill(op.path, world),
        json=_fill(op.json, world) if op.json is not None else None,
        content=op.content,
        headers=headers or None,
    )
    assert r.status_code < 500, f"{role}: {r.status_code} {r.text[:200]}"
    if op.access == "CREDENTIAL":
        assert r.status_code == 401, f"{role}: {r.status_code} {r.text[:200]}"
    elif role in ALLOWED[op.access]:
        assert r.status_code not in (401, 403), f"{role} should be allowed: {r.status_code} {r.text[:200]}"
    else:
        expected = 401 if role == "anonymous" else 403
        assert r.status_code == expected, f"{role} should be denied with {expected}: got {r.status_code} {r.text[:200]}"
