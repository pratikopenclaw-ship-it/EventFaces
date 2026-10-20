#!/bin/sh
# Registers this container on the tailnet and keeps Funnel pointed at the dev `web`
# container, re-applying it if a sleep/wake or network change drops it.
set -e

TS_HOSTNAME="${TS_HOSTNAME:-eventface}"
BACKEND="http://web:3000"
SOCK=/var/run/tailscale/tailscaled.sock
# tailscaled's output, copied here so the watchdog can spot control-plane errors that
# `tailscale status` doesn't surface (it keeps reporting "Running" for a deleted node).
TSD_LOG=/tmp/tailscaled.log
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"

log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*"; }
ts() { tailscale --socket="$SOCK" "$@"; }

if [ -z "$TS_AUTHKEY" ]; then
  log "ERROR: TS_AUTHKEY not set (add it to .env, or the file passed with --env-file)"
  exit 1
fi

log "Starting tailscaled..."
mkdir -p /var/run/tailscale
rm -f "$SOCK"
: > "$TSD_LOG"
tailscaled --socket="$SOCK" --statedir="$TS_STATE_DIR" --tun=userspace-networking 2>&1 | tee -a "$TSD_LOG" &

sleep 5
log "Authenticating with Tailscale as $TS_HOSTNAME..."
ts up --authkey="$TS_AUTHKEY" --hostname="$TS_HOSTNAME" --accept-routes --accept-dns=false

apply_funnel() {
  log "Applying funnel: 443 -> $BACKEND"
  ts funnel reset || true
  ts funnel --bg --https 443 "$BACKEND"
}

reconnect() {
  log "WARNING: $1, re-authenticating..."
  # --force-reauth registers again with the auth key even when the local state still
  # holds a node key, which is what recovers a node the tailnet has removed.
  if ts up --force-reauth --authkey="$TS_AUTHKEY" --hostname="$TS_HOSTNAME" --accept-routes --accept-dns=false; then
    apply_funnel
  else
    log "ERROR: re-authentication failed. If the auth key expired or was single-use," \
      "create a reusable, non-ephemeral key, put it in TS_AUTHKEY and recreate this container."
  fi
}

apply_funnel

log "Monitoring funnel + connectivity..."
last=$(date +%s)
while true; do
  sleep "$CHECK_INTERVAL"
  now=$(date +%s)
  elapsed=$((now - last))
  last=$now

  recent=$(cat "$TSD_LOG")
  : > "$TSD_LOG"

  # A Mac sleep/wake can leave tailscaled's control-plane connection stale without the
  # container itself crashing or exiting, so `restart: unless-stopped` never fires; poll
  # actual backend state (not just local funnel config) and force a reconnect if it drops.
  if ! ts status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
    reconnect "not connected to the coordination server"
    continue
  fi
  # A node that was offline for a while (an ephemeral key, or removed in the admin
  # console) is deleted from the tailnet; tailscaled then only logs "node not found".
  if echo "$recent" | grep -q "node not found"; then
    reconnect "this node was removed from the tailnet"
    continue
  fi
  # The loop sleeping much longer than asked means the host slept. Re-assert the
  # registration and funnel rather than waiting for a failure to show up.
  if [ "$elapsed" -gt $((CHECK_INTERVAL * 3)) ]; then
    log "Host was asleep for ~$((elapsed / 60)) min, refreshing funnel..."
    ts up --authkey="$TS_AUTHKEY" --hostname="$TS_HOSTNAME" --accept-routes --accept-dns=false || true
    apply_funnel
    continue
  fi
  if ! ts funnel status | grep -q "$BACKEND"; then
    log "WARNING: funnel config missing, reapplying..."
    apply_funnel
  fi
done
