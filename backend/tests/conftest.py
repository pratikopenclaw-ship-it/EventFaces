import os

# Point the app at the test database / Redis DB *before* anything imports settings.
os.environ["ENVIRONMENT"] = "test"
# The app under test connects as the least-privilege role (proves it works with DML only);
# schema setup and between-test cleanup use the owner.
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
OWNER_URL = os.environ.get("TEST_MIGRATION_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
os.environ["MIGRATION_DATABASE_URL"] = OWNER_URL
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://redis:6379/15")
os.environ["S3_BUCKET"] = "eventfaces-test"
# Tests PUT to presigned URLs from inside the container, so sign for the internal host.
os.environ["S3_PUBLIC_ENDPOINT_URL"] = os.environ.get("S3_ENDPOINT_URL", "http://s3:8333")
# Only client_email is read unless a real Drive client is built; tests use a fake Drive.
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = '{"client_email": "importer@test-project.iam.gserviceaccount.com"}'
os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = ""
# Test selfies are upscaled crops of a group photo (the only face imagery we can ship),
# which pose-estimate and detect a little worse than real webcam frames. Three selfie
# limits are relaxed for them; production keeps the defaults in config.py. Tests of the
# quality gate itself set thresholds explicitly.
os.environ["SELFIE_FRONT_MAX_YAW"] = "15"
os.environ["SELFIE_SIDE_MIN_YAW"] = "3"
os.environ["SELFIE_MIN_DET_SCORE"] = "0.75"

from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core import storage
from app.core.db import SessionLocal, engine
from app.core.email import Mail, set_mailer
from app.core.redis import get_redis
from app.core.security import CSRF_HEADER, hash_password, utcnow
from app.main import app
from app.models import (
    Event,
    EventMember,
    JoinMode,
    MemberRole,
    MemberStatus,
    User,
    UserRole,
)
from app.services import drive
from app.services.events import generate_access_code, generate_slug
from app.workers.celery_app import celery_app

# Run Celery tasks inline so API → task → pipeline flows are testable end to end.
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

PASSWORD = "correct-horse-battery"


class FakeMailer:
    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.outbox.append(mail)

    def last_link_token(self, to: str) -> str:
        mail = next(m for m in reversed(self.outbox) if m.to == to)
        return mail.body.split("token=")[1].split()[0]


owner_engine = create_engine(OWNER_URL, pool_pre_ping=True)


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> Iterator[None]:
    engine.dispose()
    with owner_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = OWNER_URL
    command.upgrade(cfg, "head")
    storage.ensure_bucket()
    yield


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    with owner_engine.begin() as conn:
        # Owner-only: the app role has no TRUNCATE, and the audit guard blocks deletes.
        conn.execute(text("ALTER TABLE search_audit DISABLE TRIGGER search_audit_guard"))
        conn.execute(
            text(
                "TRUNCATE users, auth_tokens, events, event_members, photos, faces, "
                "drive_sync_runs, search_grants, search_audit, invites, photo_reports, removal_requests CASCADE"
            )
        )
        conn.execute(text("ALTER TABLE search_audit ENABLE TRIGGER search_audit_guard"))
    get_redis().flushdb()
    drive.set_drive_client(None)
    storage.delete_prefix("events/")


@pytest.fixture
def mailer() -> FakeMailer:
    fake = FakeMailer()
    set_mailer(fake)
    return fake


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def new_client() -> TestClient:
    client = TestClient(app)
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    client.headers[CSRF_HEADER] = token
    return client


@pytest.fixture
def client(mailer: FakeMailer) -> TestClient:
    return new_client()


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def _make(email: str, role: UserRole = UserRole.attendee, verified: bool = True) -> User:
        user = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            role=role,
            email_verified_at=utcnow() if verified else None,
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def login_as(mailer: FakeMailer) -> Callable[[User], TestClient]:
    def _login(user: User) -> TestClient:
        c = new_client()
        r = c.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return c

    return _login


@pytest.fixture
def make_event(db: Session) -> Callable[..., Event]:
    def _make(name: str = "Summer Party", **kwargs) -> Event:
        event = Event(
            name=name,
            slug=generate_slug(name),
            access_code=generate_access_code(),
            join_mode=kwargs.pop("join_mode", JoinMode.code),
            **kwargs,
        )
        db.add(event)
        db.commit()
        return event

    return _make


@pytest.fixture
def add_member(db: Session) -> Callable[..., EventMember]:
    def _add(
        event: Event,
        user: User,
        role: MemberRole = MemberRole.attendee,
        status: MemberStatus = MemberStatus.approved,
        expires_in: timedelta | None = None,
    ) -> EventMember:
        m = EventMember(
            event_id=event.id,
            user_id=user.id,
            role=role,
            status=status,
            expires_at=utcnow() + expires_in if expires_in is not None else None,
        )
        db.add(m)
        db.commit()
        return m

    return _add
