"""least-privilege app role; append-only search audit

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29

- The application connects as `eventfaces_app` (DML only). Migrations run as the owner.
- `search_audit` is append-only for everyone: rows may only be anonymized (user_id /
  event_id set to NULL, as account and event deletion do) and deleted only once older
  than 30 days (retention). A compromised app cannot rewrite or erase recent history.
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "eventfaces_app"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
          END IF;
        END $$;
        """
    )
    password = os.environ.get("APP_DB_PASSWORD")
    if password:
        # Passed as a bound parameter into a transaction-local setting, then quoted with
        # format(%L): the secret is never spliced into SQL text.
        op.get_bind().exec_driver_sql("SELECT set_config('eventfaces.app_pw', %(pw)s, true)", {"pw": password})
        op.execute(
            f"DO $$ BEGIN EXECUTE format('ALTER ROLE {APP_ROLE} PASSWORD %L', "
            "current_setting('eventfaces.app_pw')); END $$;"
        )

    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT CONNECT ON DATABASE \"{op.get_bind().engine.url.database}\" TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT ON alembic_version TO {APP_ROLE}")
    # Tables created by later migrations (as the owner) get the same DML grants.
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION search_audit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.match_count IS DISTINCT FROM OLD.match_count
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR (NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL)
               OR (NEW.event_id IS DISTINCT FROM OLD.event_id AND NEW.event_id IS NOT NULL) THEN
              RAISE EXCEPTION 'search_audit is append-only (only anonymization is allowed)'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
          ELSIF TG_OP = 'DELETE' THEN
            IF OLD.created_at > now() - interval '30 days' THEN
              RAISE EXCEPTION 'search_audit rows younger than 30 days cannot be deleted'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN OLD;
          END IF;
          RETURN NULL;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS search_audit_guard ON search_audit")
    op.execute(
        "CREATE TRIGGER search_audit_guard BEFORE UPDATE OR DELETE ON search_audit "
        "FOR EACH ROW EXECUTE FUNCTION search_audit_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS search_audit_guard ON search_audit")
    op.execute("DROP FUNCTION IF EXISTS search_audit_guard()")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {APP_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE CONNECT ON DATABASE \"{op.get_bind().engine.url.database}\" FROM {APP_ROLE}")
    op.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
