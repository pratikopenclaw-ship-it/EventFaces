#!/usr/bin/env bash
# Backup/restore drill against the local docker-compose stack (test data only).
#
#   1. build a populated database (all migrations + a row in every table)
#   2. pg_dump -Fc it, restore into a fresh database with pg_restore
#   3. compare every table's row count + content hash, the vectors (a nearest-neighbour
#      query), the audit trigger, and that the least-privilege app role still works
#
# Usage: scripts/backup_restore_drill.sh      (needs `docker compose up -d db api`)
set -euo pipefail
cd "$(dirname "$0")/.."

PGUSER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2)
SRC=eventfaces_drill_src
DST=eventfaces_drill_dst
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

psql_admin() { docker compose exec -T db psql -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 -qAt -c "$1"; }

echo "==> fresh source and target databases"
for db in "$SRC" "$DST"; do psql_admin "DROP DATABASE IF EXISTS $db WITH (FORCE)"; done
psql_admin "CREATE DATABASE $SRC"

echo "==> migrate + populate source"
docker compose exec -T -e DRILL_DB="$SRC" api python - <<'PY'
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from tests.migration_data import populate

url = make_url(os.environ["TEST_MIGRATION_DATABASE_URL"]).set(database=os.environ["DRILL_DB"])
cfg = Config("alembic.ini")
cfg.attributes["database_url"] = url.render_as_string(hide_password=False)
command.upgrade(cfg, "head")
with Session(create_engine(url)) as s:
    populate(s)
print("populated")
PY

echo "==> backup (pg_dump -Fc)"
docker compose exec -T db pg_dump -U "$PGUSER" -Fc "$SRC" > "$WORK/backup.dump"
echo "    $(wc -c < "$WORK/backup.dump" | tr -d ' ') bytes"

echo "==> restore into a new database (pg_restore)"
psql_admin "CREATE DATABASE $DST"
docker compose exec -T db pg_restore -U "$PGUSER" -d "$DST" --exit-on-error < "$WORK/backup.dump"

echo "==> verify"
docker compose exec -T -e SRC="$SRC" -e DST="$DST" api python - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from tests.migration_data import fingerprint

owner = make_url(os.environ["TEST_MIGRATION_DATABASE_URL"])
app = make_url(os.environ["TEST_DATABASE_URL"])  # the least-privilege eventfaces_app role
src, dst = (create_engine(owner.set(database=os.environ[k])) for k in ("SRC", "DST"))
problems = []
with src.connect() as a, dst.connect() as b:
    fa, fb = fingerprint(a), fingerprint(b)
    for t in sorted(set(fa) | set(fb)):
        ok = fa.get(t) == fb.get(t)
        print(f"    {'ok ' if ok else 'BAD'} {t:18} rows={fb.get(t, (None,))[0]}")
        ok or problems.append(f"table {t} differs")
    q = text("SELECT photo_id FROM faces ORDER BY embedding <=> (SELECT embedding FROM faces LIMIT 1) LIMIT 1")
    if a.execute(q).scalar() != b.execute(q).scalar():
        problems.append("vector search differs")
    for name, sql in {
        "audit trigger": "SELECT count(*) FROM pg_trigger WHERE tgname = 'search_audit_guard'",
        "hnsw index": "SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_faces_embedding_hnsw'",
        "alembic head": "SELECT count(*) FROM alembic_version",
    }.items():
        if b.execute(text(sql)).scalar() != 1:
            problems.append(f"{name} missing after restore")

# The app connects as eventfaces_app: it must be able to work, and still not rewrite audit rows.
try:
    with create_engine(app.set(database=os.environ["DST"])).begin() as c:
        c.execute(text("UPDATE users SET email = email"))
        print("    ok  app role can connect and write")
except Exception as e:  # noqa: BLE001
    problems.append(f"app role cannot use the restored database: {type(e).__name__}: {str(e).splitlines()[0]}")
try:
    with create_engine(app.set(database=os.environ["DST"])).begin() as c:
        c.execute(text("UPDATE search_audit SET match_count = match_count + 1"))
    problems.append("audit log is writable by the app role after restore")
except Exception:  # noqa: BLE001
    print("    ok  audit log still append-only for the app role")

if problems:
    print("DRILL FAILED:\n  - " + "\n  - ".join(problems))
    sys.exit(1)
print("DRILL PASSED")
PY

echo "==> clean up"
for db in "$SRC" "$DST"; do psql_admin "DROP DATABASE IF EXISTS $db WITH (FORCE)"; done
