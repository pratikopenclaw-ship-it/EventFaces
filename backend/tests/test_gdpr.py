"""GDPR behaviours not covered elsewhere (Phase B §8): erasure for staff accounts, storage
limitation for removal requests, and event deletion leaving no personal or biometric rows."""

from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.security import hash_token, utcnow
from app.models import (
    DriveSyncRun,
    Event,
    Invite,
    PhotoReport,
    RemovalRequest,
    RemovalStatus,
    User,
    UserRole,
)
from app.services.retention import run_retention
from tests.conftest import PASSWORD
from tests.test_authz_matrix import World, world  # noqa: F401  (fixture re-export)


def _login(email: str):  # type: ignore[no-untyped-def]
    from tests.conftest import new_client

    c = new_client()
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


def test_organizer_can_erase_their_account_and_history_is_kept_without_them(world: World, db: Session) -> None:  # noqa: F811
    org = world.users["organizer_this"]
    org_id, org_email = org.id, org.email
    world.invite_a.invited_by = org.id
    world.report_a.resolved_by = org.id
    db.merge(world.invite_a)
    db.merge(world.report_a)
    db.add(DriveSyncRun(event_id=world.event_a.id, started_by=org.id, folder_id=world.event_a.drive_folder_id))
    db.commit()

    c = _login(org_email)
    r = c.request("DELETE", "/api/me", json={"password": PASSWORD})
    assert r.status_code == 200, r.text

    db.expire_all()
    assert db.get(User, org_id) is None
    assert db.get(Invite, world.invite_a.id).invited_by is None
    assert db.get(PhotoReport, world.report_a.id).resolved_by is None
    assert db.scalar(select(func.count()).select_from(DriveSyncRun).where(DriveSyncRun.started_by == org_id)) == 0
    # The event itself (owned by the organisation, not the person) survives.
    assert db.get(Event, world.event_a.id) is not None


def test_removal_requests_are_purged_after_their_retention(db: Session, world: World) -> None:  # noqa: F811
    from app.core.config import get_settings

    now = utcnow()
    s = get_settings()

    def req(status: RemovalStatus, created: timedelta, resolved: timedelta | None) -> RemovalRequest:
        r = RemovalRequest(
            event_id=world.event_a.id,
            email=f"p{status.value}{created.days}@example.com",
            token_hash=hash_token(f"{status}{created}{resolved}"),
            status=status,
            matched_photo_ids=[],
        )
        r.created_at = now - created
        r.resolved_at = now - resolved if resolved is not None else None
        db.add(r)
        return r

    stale_unverified = req(RemovalStatus.unverified, timedelta(hours=s.removal_token_hours + 1), None)
    fresh_unverified = req(RemovalStatus.unverified, timedelta(hours=1), None)
    old_resolved = req(RemovalStatus.resolved, timedelta(days=400), timedelta(days=s.removal_request_retention_days + 1))
    recent_resolved = req(RemovalStatus.declined, timedelta(days=5), timedelta(days=1))
    open_old = req(RemovalStatus.submitted, timedelta(days=400), None)  # still needs an organizer
    db.commit()
    ids = {k: v.id for k, v in locals().items() if isinstance(v, RemovalRequest)}

    run_retention(db)
    db.expire_all()
    left = set(db.scalars(select(RemovalRequest.id)))
    assert ids["stale_unverified"] not in left and ids["old_resolved"] not in left
    assert {ids["fresh_unverified"], ids["recent_resolved"], ids["open_old"]} <= left


def test_event_deletion_leaves_no_personal_or_biometric_rows(world: World, db: Session) -> None:  # noqa: F811
    admin = _login("admin@example.com")
    event_id = world.event_a.id
    assert admin.delete(f"/api/events/{event_id}").status_code == 204
    db.expire_all()
    # Every table with an event_id column: no row may still point at the event.
    tables = db.execute(
        text("SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='event_id'")
    ).scalars()
    leftovers = {
        t: db.execute(text(f'SELECT count(*) FROM "{t}" WHERE event_id = :e'), {"e": event_id}).scalar()  # noqa: S608 - names from information_schema
        for t in tables
    }
    assert not {t: n for t, n in leftovers.items() if n}, leftovers
    # People stay (they may belong to other events); their link to the event is gone.
    assert db.get(User, world.users["attendee_member"].id) is not None


def test_last_super_admin_rule_does_not_block_organizers(world: World) -> None:  # noqa: F811
    assert world.users["organizer_other"].role == UserRole.organizer
    c = _login(world.users["organizer_other"].email)
    assert c.request("DELETE", "/api/me", json={"password": PASSWORD}).status_code == 200
