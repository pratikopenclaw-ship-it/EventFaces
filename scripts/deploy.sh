#!/usr/bin/env bash
# Deploy a release tag on the server, with automatic rollback (DEPLOYMENT.md "Release").
#   scripts/deploy.sh v1.4.0
#
#  1. checks: annotated tag, clean checkout, .env.prod present
#  2. pre-deploy database backup (pg_dump -Fc, kept in .deploy/, mode 600)
#  3. check out the tag, build the images with APP_VERSION=<tag>
#  4. start; the API runs `alembic upgrade head` on start; wait until every service is healthy
#  5. scripts/release_check.sh against FRONTEND_URL, expecting version <tag>
#  On any failure after step 2: roll back to the previous release. A schema change is undone
#  with `alembic downgrade` (keeps writes made since the deploy); if that fails, the backup
#  from step 2 is restored.
#
# Env: COMPOSE_FILE (docker-compose.prod.yml[:override.yml]), STATE_DIR (.deploy),
#      BASE_URL (default FRONTEND_URL from ENV_FILE), ERRORS_URL (default https://errors.$DOMAIN),
#      SKIP_FETCH=1 (don't `git fetch`; for local rehearsals).
set -Eeuo pipefail  # -E: the ERR trap (automatic rollback) also fires inside functions
cd "$(dirname "$0")/.."

ENV_FILE=.env.prod  # fixed: docker-compose.prod.yml reads it by name (env_file)
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"  # docker's own variable; ":" adds overrides
STATE_DIR="${STATE_DIR:-.deploy}"
HISTORY="$STATE_DIR/history"   # lines: <utc time> <tag> <alembic revision> [rollback]
KEEP_DUMPS=3                   # dumps contain face embeddings: keep few, delete with care

val() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true; }
compose() { docker compose --env-file "$ENV_FILE" "$@"; }
log() { printf '\n==> %s\n' "$*"; }
die() { printf 'deploy: %s\n' "$*" >&2; exit 1; }

PGUSER="$(val POSTGRES_USER)"
PGDB="$(val POSTGRES_DB)"
BASE_URL="${BASE_URL:-$(val FRONTEND_URL)}"
DOMAIN="$(val DOMAIN)"
export ERRORS_URL="${ERRORS_URL:-${DOMAIN:+https://errors.$DOMAIN}}"

db_revision() { compose exec -T db psql -U "$PGUSER" -d "$PGDB" -Atc "SELECT version_num FROM alembic_version" 2>/dev/null || true; }
# Pre-deploy dumps, oldest first (names start with a UTC timestamp, so glob order is age order).
dumps() { local f; for f in "$STATE_DIR"/predeploy-*.dump; do [ -e "$f" ] && echo "$f"; done; return 0; }
prune_dumps() { # keep the newest KEEP_DUMPS (they hold biometric data; DEPLOYMENT.md: at most 30 days)
  dumps | awk -v keep="$KEEP_DUMPS" '{ l[NR] = $0 } END { for (i = 1; i <= NR - keep; i++) print l[i] }' | while read -r old; do
    shred -u "$old" 2>/dev/null || rm -f "$old"
  done
}
previous_tag() { [ -f "$HISTORY" ] && tail -1 "$HISTORY" | awk '{print $2}' || true; }

start_release() { # start_release <tag>: build and start that checkout, then smoke-check it
  local tag="$1"
  log "build $tag"
  APP_VERSION="$tag" compose build
  log "start $tag (migrations run on API start)"
  APP_VERSION="$tag" compose up -d --remove-orphans --wait --wait-timeout 900
  log "release check"
  scripts/release_check.sh "$BASE_URL" "$tag"
}

restore_backup() { # restore_backup <dump>
  local dump="$1"
  [ -s "$dump" ] || die "no backup to restore ($dump): restore manually (DEPLOYMENT.md section 7)"
  log "restore database from $dump"
  compose stop api worker beat web
  compose exec -T db psql -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE \"$PGDB\" WITH (FORCE)" -c "CREATE DATABASE \"$PGDB\""
  compose exec -T db pg_restore -U "$PGUSER" -d "$PGDB" --exit-on-error <"$dump"
  # Database-level grants are not in the dump: same as migration 0007 + glitchtip-db.sh.
  compose exec -T db psql -U "$PGUSER" -d "$PGDB" -v ON_ERROR_STOP=1 \
    -c "GRANT CONNECT ON DATABASE \"$PGDB\" TO eventfaces_app" -c "REVOKE CONNECT ON DATABASE \"$PGDB\" FROM PUBLIC"
}

rollback() { # rollback <to-tag> <alembic revision before> <dump>
  local target="$1" rev_before="$2" dump="$3" rev_now
  trap - ERR
  [ -n "$target" ] || die "first deploy failed: nothing to roll back to (fix and deploy again)"
  log "ROLLBACK to $target"
  rev_now="$(db_revision)"
  if [ -n "$rev_before" ] && [ -n "$rev_now" ] && [ "$rev_now" != "$rev_before" ]; then
    log "schema changed ($rev_before -> $rev_now): downgrade with the new release's migrations"
    compose stop api worker beat
    if ! compose run --rm --no-deps -T api alembic downgrade "$rev_before"; then
      restore_backup "$dump"
    fi
  fi
  git checkout --quiet --detach "$target"
  start_release "$target" || die "rollback to $target failed its release check: investigate now"
  printf '%s %s %s rollback\n' "$(date -u +%FT%TZ)" "$target" "$(db_revision)" >>"$HISTORY"
  prune_dumps
  log "rolled back to $target"
}

# --- rollback.sh entry point: roll back to the release before the current one ---
if [ "${1:-}" = "--rollback" ]; then
  [ -f "$HISTORY" ] || die "no deploy history"
  if [ -z "${2:-}" ] && [ "$(tail -1 "$HISTORY" | awk '{print $4}')" = rollback ]; then
    # The line before a rollback is the release that was rolled back: never guess it.
    die "the last change was already a rollback: name the tag (scripts/rollback.sh vX.Y.Z)"
  fi
  target="${2:-$(tail -2 "$HISTORY" | head -1 | awk '{print $2}')}"
  grep -q " $target " "$HISTORY" || die "$target was never deployed here"
  [ "$target" != "$(previous_tag)" ] || die "$target is already deployed"
  rev_target="$(awk -v t="$target" '$2 == t {r=$3} END {print r}' "$HISTORY")"
  dump="$(dumps | tail -1)"
  rollback "$target" "$rev_target" "$dump"
  exit 0
fi

TAG="${1:?usage: scripts/deploy.sh <tag>   |   scripts/rollback.sh [tag]}"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || die "tag must look like v1.2.3 or v1.2.3-rc.1"

log "preflight"
[ -f "$ENV_FILE" ] || die "$ENV_FILE missing"
[ -n "$BASE_URL" ] || die "FRONTEND_URL missing in $ENV_FILE"
if ! git diff --quiet || ! git diff --cached --quiet; then die "the checkout has local changes"; fi
[ "${SKIP_FETCH:-0}" = 1 ] || git fetch --quiet --tags origin
[ "$(git cat-file -t "$TAG" 2>/dev/null)" = tag ] || die "$TAG is not an annotated tag (use scripts/release.sh)"
mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"
PREV="$(previous_tag)"
[ "$PREV" != "$TAG" ] || die "$TAG is already deployed"

DUMP=""
REV_BEFORE=""
if compose ps --status running --services 2>/dev/null | grep -qx db; then
  REV_BEFORE="$(db_revision)"
  DUMP="$STATE_DIR/predeploy-$(date -u +%Y%m%dT%H%M%SZ)-${PREV:-none}.dump"
  log "backup database (revision ${REV_BEFORE:-none}) to $DUMP"
  (umask 077 && compose exec -T db pg_dump -U "$PGUSER" -Fc "$PGDB" >"$DUMP")
  [ -s "$DUMP" ] || die "backup is empty: not deploying"
fi

trap 'echo "deploy of $TAG failed" >&2; rollback "$PREV" "$REV_BEFORE" "$DUMP"; exit 1' ERR
git checkout --quiet --detach "$TAG"
start_release "$TAG"
trap - ERR

printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$TAG" "$(db_revision)" >>"$HISTORY"
prune_dumps
log "deployed $TAG (previous: ${PREV:-none})"
