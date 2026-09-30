"""API server for the Playwright end-to-end suite (test-only; never part of the app).

Runs the real FastAPI app against the *test* database, Redis DB and bucket, with:
- Celery tasks inline (eager), so Drive sync and indexing happen within the request;
- a fake Google Drive (the brief: "mocked Drive API") holding group-photo fixtures;
- a captured mailbox instead of SMTP;
- a few /__e2e control endpoints (reset, seed, read mail, fixture images, expire event).

    docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api web
"""

import os

# Same environment the pytest suite uses (see conftest.py), set before app imports.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
OWNER_URL = os.environ.get("TEST_MIGRATION_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
os.environ["MIGRATION_DATABASE_URL"] = OWNER_URL
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://redis:6379/15")
os.environ["S3_BUCKET"] = "eventfaces-e2e"
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = '{"client_email": "importer@e2e-project.iam.gserviceaccount.com"}'
os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = ""
# The relaxed selfie limits conftest.py documents (fixture selfies are upscaled crops);
# override .env, exactly as the pytest suite does.
os.environ["SELFIE_FRONT_MAX_YAW"] = "15"
os.environ["SELFIE_SIDE_MIN_YAW"] = "3"
os.environ["SELFIE_MIN_DET_SCORE"] = "0.75"

import uuid
from datetime import timedelta

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import create_engine, text

from app.core import storage
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.email import Mail, set_mailer
from app.core.redis import get_redis
from app.core.security import hash_password, utcnow
from app.main import app
from app.models import Event, EventMember, JoinMode, MemberRole, MemberStatus, ModerationMode, User, UserRole
from app.services import drive
from app.services.events import generate_access_code, generate_slug
from app.workers.celery_app import celery_app
from tests.helpers import FakeDrive, group_photo_bytes, half_photo, selfie_set, solid_jpeg

assert get_settings().environment == "test", "the e2e server must never run in production"  # nosec B101

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

PASSWORD = "e2e-password-123"
BLUR_RADIUS = 3
FOLDER = "1E2EFolderAAAAAAAAAA"
USERS = {
    "admin@e2e.test": UserRole.super_admin,
    "org@e2e.test": UserRole.organizer,
    "alice@e2e.test": UserRole.attendee,  # the person on the left of the group photo
    "bob@e2e.test": UserRole.attendee,
}


class Outbox:
    def __init__(self) -> None:
        self.mails: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.mails.append(mail)


outbox = Outbox()
set_mailer(outbox)
owner_engine = create_engine(OWNER_URL, pool_pre_ping=True)


def migrate_fresh() -> None:
    engine.dispose()
    with owner_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = OWNER_URL
    command.upgrade(cfg, "head")
    storage.ensure_bucket()
    storage.configure_cors([get_settings().frontend_url])


def reset() -> None:
    with owner_engine.begin() as conn:
        conn.execute(text("ALTER TABLE search_audit DISABLE TRIGGER search_audit_guard"))
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")).scalars()
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))
        conn.execute(text("ALTER TABLE search_audit ENABLE TRIGGER search_audit_guard"))
    get_redis().flushdb()
    storage.delete_prefix("events/")
    outbox.mails.clear()
    drive.set_drive_client(
        FakeDrive({FOLDER: {"left": ("left.jpg", half_photo("left")), "right": ("right.jpg", half_photo("right")), "group": ("group.jpg", group_photo_bytes())}})
    )
    with SessionLocal() as db:
        for email, role in USERS.items():
            db.add(User(email=email, password_hash=hash_password(PASSWORD), role=role, email_verified_at=utcnow()))
        db.commit()


router = APIRouter(prefix="/__e2e")


@router.post("/reset")
def reset_endpoint() -> dict[str, object]:
    release_face_slots()
    reset()
    return {"password": PASSWORD, "users": list(USERS), "folder": FOLDER}


@router.post("/event")
def seed_event(join_mode: str = "code", guest_uploads: bool = False, moderation: str = "manual", synced: bool = True) -> dict[str, str]:
    """An event run by org@e2e.test, with alice and bob as members, photos synced."""
    from app.models import DriveSyncRun, SyncStatus
    from app.workers.tasks import sync_drive

    with SessionLocal() as db:
        name = f"E2E Party {uuid.uuid4().hex[:4]}"
        ev = Event(
            name=name,
            slug=generate_slug(name),
            access_code=generate_access_code(),
            join_mode=JoinMode(join_mode),
            guest_upload_enabled=guest_uploads,
            moderation_mode=ModerationMode(moderation),
            drive_folder_id=FOLDER,
        )
        db.add(ev)
        db.flush()
        users = {u.email: u for u in db.query(User).all()}
        db.add(EventMember(event_id=ev.id, user_id=users["org@e2e.test"].id, role=MemberRole.organizer, status=MemberStatus.approved))
        for email in ("alice@e2e.test", "bob@e2e.test"):
            db.add(EventMember(event_id=ev.id, user_id=users[email].id, role=MemberRole.attendee, status=MemberStatus.approved))
        db.commit()
        if synced:
            run = DriveSyncRun(event_id=ev.id, folder_id=FOLDER, status=SyncStatus.queued, started_by=users["org@e2e.test"].id)
            db.add(run)
            db.commit()
            sync_drive.delay(str(run.id))  # eager: import + index happen here
        return {"id": str(ev.id), "slug": ev.slug, "code": ev.access_code, "name": name}


@router.post("/event/{event_id}/users")
def seed_users(event_id: uuid.UUID, n: int = 100) -> dict[str, object]:
    """Load-test users: verified, consented, approved members of the event."""
    from app.services.search import FACE_CONSENT_VERSION

    pw = hash_password(PASSWORD)  # hash once: argon2 per user would dominate seeding
    emails = [f"load{i:04d}@example.com" for i in range(min(n, 2000))]
    with SessionLocal() as db:
        now = utcnow()
        for email in emails:
            u = User(email=email, password_hash=pw, role=UserRole.attendee, email_verified_at=now, face_consent_at=now, face_consent_version=FACE_CONSENT_VERSION)
            db.add(u)
            db.flush()
            db.add(EventMember(event_id=event_id, user_id=u.id, role=MemberRole.attendee, status=MemberStatus.approved))
        db.commit()
    return {"emails": emails, "password": PASSWORD}


@router.post("/event/{event_id}/expire")
def expire_event(event_id: uuid.UUID) -> dict[str, str]:
    with SessionLocal() as db:
        ev = db.get(Event, event_id)
        if ev is None:
            raise HTTPException(404)
        ev.access_expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    return {"ok": "expired"}


_held_slots = 0


@router.post("/face-slots/hold")
def hold_face_slots() -> dict[str, int]:
    """Take every face-work slot: the server looks saturated (searches get queued)."""
    global _held_slots
    from app.core import face_slots

    while face_slots.try_acquire_now():
        _held_slots += 1
    return {"held": _held_slots}


@router.post("/face-slots/release")
def release_face_slots() -> dict[str, int]:
    global _held_slots
    from app.core import face_slots

    released = _held_slots
    for _ in range(_held_slots):
        face_slots.release()
    _held_slots = 0
    return {"released": released}


@router.get("/mail")
def last_mail(to: str) -> dict[str, str]:
    for mail in reversed(outbox.mails):
        if mail.to == to:
            return {"subject": mail.subject, "body": mail.body}
    raise HTTPException(404, "no mail")


@router.get("/selfie/{shot}.jpg")
def selfie(shot: str) -> Response:
    """Frames for the fake camera: alice's front/left/right, plus a too-dark frame."""
    if shot == "dark":
        import io

        from PIL import Image, ImageEnhance

        frame = dict(selfie_set(0))["front"]
        img = ImageEnhance.Brightness(Image.open(io.BytesIO(frame))).enhance(0.25)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        data = out.getvalue()
    elif shot == "blurry":
        # Passes the browser's live guidance (pose, size, light) but fails the server's
        # sharpness check: drives the "server rejects what the client accepted" path.
        import io

        from PIL import Image, ImageFilter

        frame = dict(selfie_set(0))["front"]
        img = Image.open(io.BytesIO(frame)).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        data = out.getvalue()
    elif shot == "blank":
        data = solid_jpeg((70, 70, 70), (640, 480))
    else:
        data = dict(selfie_set(0)).get(shot) or b""
        if not data:
            raise HTTPException(404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/guest-photo.jpg")
def guest_photo() -> Response:
    return Response(half_photo("left"), media_type="image/jpeg")


app.include_router(router)

if __name__ == "__main__":
    migrate_fresh()
    reset()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")  # noqa: S104  # nosec B104 - container-internal
