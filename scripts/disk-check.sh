#!/usr/bin/env bash
# Disk and memory check for the server, run from cron every 10 minutes:
#   */10 * * * * deploy /home/deploy/EventFaces/scripts/disk-check.sh
# Checks in with a GlitchTip heartbeat monitor ONLY while everything is fine, so GlitchTip
# alerts both when a disk fills up and when this check stops running.
#   DISK_HEARTBEAT_URL   check-in URL of the "disk" heartbeat monitor (from .env.prod)
#   DISK_MAX_PERCENT     default 80
#   MEM_MAX_PERCENT      default 90
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env.prod}"
val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true; }
URL="${DISK_HEARTBEAT_URL:-$(val DISK_HEARTBEAT_URL)}"
DISK_MAX="${DISK_MAX_PERCENT:-80}"
MEM_MAX="${MEM_MAX_PERCENT:-90}"

problems=()
# Root filesystem and Docker's data directory (volumes: Postgres, uploads).
for mount in / "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"; do
  [ -d "$mount" ] || continue
  used=$(df -P "$mount" | awk 'NR==2 {gsub("%", "", $5); print $5}')
  if [ "$used" -ge "$DISK_MAX" ]; then problems+=("disk $mount at ${used}%"); fi
done
if [ -r /proc/meminfo ]; then
  mem=$(awk '/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END {printf "%d", (t-a)*100/t}' /proc/meminfo)
  if [ "$mem" -ge "$MEM_MAX" ]; then problems+=("memory at ${mem}%"); fi
fi

if [ ${#problems[@]} -gt 0 ]; then
  echo "disk-check: ${problems[*]} (no check-in; GlitchTip will alert)" >&2
  exit 1
fi
if [ -n "$URL" ]; then
  curl -fsS -m 10 -X POST -o /dev/null "$URL"
fi
echo "disk-check: ok"
