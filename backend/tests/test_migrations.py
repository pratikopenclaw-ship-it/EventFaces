"""Alembic migrations on a populated database (Phase C): every downgrade and upgrade
runs cleanly with data in place, data in surviving tables is untouched by a round trip,
and the migrated schema matches the ORM models (no drift)."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session

from app.core.db import Base
from tests.conftest import OWNER_URL
from tests.migration_data import fingerprint, populate

SCRATCH_DB = "eventfaces_migtest"


def _url(db: str) -> URL:
    return make_url(OWNER_URL).set(database=db)


@pytest.fixture
def scratch() -> Iterator[tuple[Engine, Config]]:
    admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
    url = _url(SCRATCH_DB)
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = url.render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        yield engine, cfg
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))
        admin.dispose()


def _revisions(cfg: Config) -> list[str]:
    """Oldest → newest."""
    return [r.revision for r in reversed(list(ScriptDirectory.from_config(cfg).walk_revisions()))]


def _current(engine: Engine) -> str | None:
    with engine.connect() as c:
        return MigrationContext.configure(c).get_current_revision()


def test_full_downgrade_and_upgrade_with_data(scratch: tuple[Engine, Config]) -> None:
    engine, cfg = scratch
    revs = _revisions(cfg)
    command.upgrade(cfg, "head")
    with Session(engine) as s:
        populate(s)
    with engine.connect() as c:
        before = fingerprint(c)
    assert all(n > 0 for n, _ in before.values()), {t: n for t, (n, _) in before.items() if n == 0}

    # Step down one revision at a time: each downgrade must succeed with data present,
    # and every table that still exists keeps its rows.
    for target in [*reversed(revs[:-1]), "base"]:
        command.downgrade(cfg, target)
        with engine.connect() as c:
            now = fingerprint(c)
        for table, (count, _) in now.items():
            if table in before:
                assert count == before[table][0], (target, table, count, before[table][0])
        assert _current(engine) == (None if target == "base" else target)

    command.upgrade(cfg, "head")
    assert _current(engine) == revs[-1]


@pytest.mark.parametrize("steps", [1, 2, 3])
def test_partial_round_trip_preserves_surviving_data(scratch: tuple[Engine, Config], steps: int) -> None:
    engine, cfg = scratch
    revs = _revisions(cfg)
    command.upgrade(cfg, "head")
    with Session(engine) as s:
        populate(s)
    with engine.connect() as c:
        before = fingerprint(c)
    command.downgrade(cfg, revs[-1 - steps])
    with engine.connect() as c:
        surviving = set(fingerprint(c))
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        after = fingerprint(c)
    # Tables that existed throughout keep identical row counts (columns re-added by the
    # upgrade come back NULL, so compare counts, plus exact content for untouched tables).
    for table in surviving:
        assert after[table][0] == before[table][0], (table, after[table], before[table])
    for table in ("users", "events", "photos", "faces", "event_members"):
        assert after[table] == before[table], table


def test_migrated_schema_matches_the_models(scratch: tuple[Engine, Config]) -> None:
    engine, cfg = scratch
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    assert diff == [], "\n".join(map(str, diff))


def test_migrations_leave_the_app_role_least_privileged(scratch: tuple[Engine, Config]) -> None:
    engine, cfg = scratch
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        can_update_audit = c.execute(text("SELECT has_table_privilege('eventfaces_app', 'alembic_version', 'UPDATE')")).scalar()
        is_super = c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = 'eventfaces_app'")).scalar()
        trigger = c.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname = 'search_audit_guard'")).scalar()
    assert can_update_audit is False and is_super is False and trigger == 1
