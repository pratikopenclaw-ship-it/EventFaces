#!/bin/sh
# Registers this container on the tailnet and keeps Funnel pointed at the dev `web`
# container, re-applying it if a sleep/wake or network change drops it.
set -e

TS_HOSTNAME="${TS_HOSTNAME:-eventface}"
BACKEND="http://web:3000"

log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*"; }

if [ -z "$TS_AUTHKEY" ]; then
  log "ERROR: TS_AUTHKEY not set"
  exit 1
fi

log "Starting tailscaled..."
mkdir -p /var/run/tailscale
rm -f /var/run/tailscale/tailscaled.sock
tailscaled --socket=/var/run/tailscale/tailscaled.sock --statedir="$TS_STATE_DIR" --tun=userspace-networking &

sleep 5
log "Authenticating with Tailscale as $TS_HOSTNAME..."
tailscale --socket=/var/run/tailscale/tailscaled.sock up --authkey="$TS_AUTHKEY" --hostname="$TS_HOSTNAME" --accept-routes --accept-dns=false

apply_funnel() {
  log "Applying funnel: 443 -> $BACKEND"
  tailscale --socket=/var/run/tailscale/tailscaled.sock funnel reset || true
  tailscale --socket=/var/run/tailscale/tailscaled.sock funnel --bg --https 443 "$BACKEND"
}

reconnect() {
  log "WARNING: not connected to the coordination server, re-authenticating..."
  tailscale --socket=/var/run/tailscale/tailscaled.sock up --authkey="$TS_AUTHKEY" --hostname="$TS_HOSTNAME" --accept-routes --accept-dns=false
  apply_funnel
}

apply_funnel

log "Monitoring funnel + connectivity..."
while true; do
  sleep 60
  # A Mac sleep/wake can leave tailscaled's control-plane connection stale without the
  # container itself crashing or exiting, so `restart: unless-stopped` never fires; poll
  # actual backend state (not just local funnel config) and force a reconnect if it drops.
  # Plain (non-JSON) status prints "Logged in" lines only once actually connected and
  # exits non-zero on "Tailscale is stopped"/not-running backends; avoids brittle JSON
  # key/space matching (status --json pretty-prints "BackendState": "Running" with a
  # space, which an exact-match grep silently never matches, forcing a reconnect loop
  # every poll and never giving the public Funnel DNS record a chance to settle).
  if ! tailscale --socket=/var/run/tailscale/tailscaled.sock status >/dev/null 2>&1; then
    reconnect
    continue
  fi
  if ! tailscale --socket=/var/run/tailscale/tailscaled.sock funnel status | grep -q "$BACKEND"; then
    log "WARNING: funnel config missing, reapplying..."
    apply_funnel
  fi
done
