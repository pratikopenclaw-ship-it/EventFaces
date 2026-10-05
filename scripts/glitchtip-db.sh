#!/usr/bin/env bash
# Creates (or updates the password of) GlitchTip's own role and database on the shared
# Postgres. Idempotent; run once before the first start of the glitchtip service and after
# rotating GLITCHTIP_DB_PASSWORD. The role owns only its database: no access to eventfaces.
#   scripts/glitchtip-db.sh                 # production (docker-compose.prod.yml, .env.prod)
#   COMPOSE="docker compose" ENV_FILE=.env scripts/glitchtip-db.sh   # local rehearsal
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.prod.yml --env-file $ENV_FILE}"
# Env files aren't shell syntax (e.g. EMAIL_FROM=Name <addr>): read only what we need.
val() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true; }
GLITCHTIP_DB_PASSWORD="$(val GLITCHTIP_DB_PASSWORD)"
POSTGRES_USER="$(val POSTGRES_USER)"
POSTGRES_DB="$(val POSTGRES_DB)"
: "${GLITCHTIP_DB_PASSWORD:?set GLITCHTIP_DB_PASSWORD in $ENV_FILE}"
: "${POSTGRES_USER:?}" "${POSTGRES_DB:?}"

# The password travels as an environment variable (not on any command line, so not in `ps`)
# and reaches SQL as a psql variable, quoted by psql.
export GLITCHTIP_DB_PASSWORD
$COMPOSE exec -T -e GLITCHTIP_DB_PASSWORD db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
\getenv pw GLITCHTIP_DB_PASSWORD
SELECT 'CREATE ROLE glitchtip LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'glitchtip')\gexec
ALTER ROLE glitchtip WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pw';
SELECT 'CREATE DATABASE glitchtip OWNER glitchtip' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'glitchtip')\gexec
REVOKE ALL ON DATABASE glitchtip FROM PUBLIC;
SQL
# Keep GlitchTip out of the app's database (PUBLIC may connect by default).
$COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "REVOKE CONNECT ON DATABASE \"$POSTGRES_DB\" FROM PUBLIC" >/dev/null
echo "glitchtip role and database ready"
