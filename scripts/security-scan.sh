#!/usr/bin/env bash
# Every scanner from the security audit, in one place. Runs against the local tree and
# the local docker-compose stack only. Exits non-zero if any step fails; a summary is
# printed at the end. Justified exceptions live in the tools' own config (ruff.toml,
# mypy.ini, .gitleaks.toml, eslint.config.mjs) and in SECURITY_QA_REPORT.md.
#
#   scripts/security-scan.sh           # everything except ZAP
#   scripts/security-scan.sh --zap     # also a ZAP baseline scan of the web app (compose network)
#
# Needs: docker compose stack up (api), network access for advisory databases and
# scanner rulesets (pip-audit, npm audit, semgrep registry, trivy DB).
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

RESULTS=()
step() {
  local name=$1; shift
  echo
  echo "==> $name"
  if "$@"; then RESULTS+=("PASS  $name"); else RESULTS+=("FAIL  $name"); fi
}

api() { docker compose exec -T api "$@"; }

# --- Backend ----------------------------------------------------------------------------
step "pip-audit (Python dependency CVEs)" api pip-audit --progress-spinner off --strict
step "ruff (lint incl. flake8-bandit rules)" api ruff check .
step "mypy (strict on auth/permission modules)" api mypy app
step "bandit (Python SAST)" api bandit -q -r app

# --- Frontend ---------------------------------------------------------------------------
step "npm audit (production deps, high+)" bash -c "cd frontend && npm audit --omit=dev --audit-level=high"
step "eslint (incl. eslint-plugin-security)" bash -c "cd frontend && npx eslint ."
step "tsc --noEmit" bash -c "cd frontend && npx tsc --noEmit"
step "vitest (redirect/CSP/form/key-safety unit tests)" bash -c "cd frontend && npx vitest run"

# --- Repository-wide --------------------------------------------------------------------
step "semgrep (python, owasp-top-ten, secrets, js/ts/react, dockerfile)" \
  docker run --rm -v "$ROOT:/src" -w /src semgrep/semgrep:latest semgrep scan --error --quiet \
    --config p/python --config p/owasp-top-ten --config p/secrets --config p/javascript \
    --config p/typescript --config p/react --config p/dockerfile \
    --exclude node_modules --exclude .next --exclude 'public/mediapipe' --exclude graphify-out \
    --exclude 'loadtest/results' --exclude test-results --exclude playwright-report
step "gitleaks (full git history)" \
  docker run --rm -v "$ROOT:/repo" zricethezav/gitleaks:latest git /repo --config /repo/.gitleaks.toml --redact --no-banner
step "gitleaks (working tree incl. untracked files)" \
  docker run --rm -v "$ROOT:/repo" zricethezav/gitleaks:latest dir /repo --config /repo/.gitleaks.toml --redact --no-banner
step "compose policy (digest pins, no exposed DB/Redis, hardened prod)" python3 scripts/check_compose.py

# --- Containers -------------------------------------------------------------------------
build_prod() {
  docker build -q -t eventfaces-api:prod backend >/dev/null &&
    docker build -q --target prod -t eventfaces-web:prod frontend >/dev/null
}
step "build production images" build_prod
TRIVY=(docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v eventfaces-trivy-cache:/root/.cache -v "$ROOT:/src" aquasec/trivy:latest)
step "trivy config (Dockerfiles)" "${TRIVY[@]}" config --exit-code 1 --severity HIGH,CRITICAL /src
# --ignore-unfixed: base-image packages with no upstream fix are accepted residual risk R-1.
step "trivy image: API (fixable HIGH/CRITICAL)" "${TRIVY[@]}" image --exit-code 1 --ignore-unfixed --severity HIGH,CRITICAL eventfaces-api:prod
step "trivy image: web (fixable HIGH/CRITICAL)" "${TRIVY[@]}" image --exit-code 1 --ignore-unfixed --severity HIGH,CRITICAL eventfaces-web:prod
no_test_tools() {
  ! docker run --rm --entrypoint python eventfaces-api:prod -c "import pytest" 2>/dev/null &&
    ! docker run --rm --entrypoint python eventfaces-api:prod -m pip --version 2>/dev/null
}
step "production API image ships without test tooling or pip" no_test_tools
non_root() {
  [ "$(docker run --rm --entrypoint id eventfaces-api:prod -u)" != 0 ] &&
    [ "$(docker run --rm --entrypoint id eventfaces-web:prod -u)" != 0 ]
}
step "production images run as non-root" non_root

# --- DAST (optional) --------------------------------------------------------------------
if [[ "${1:-}" == "--zap" ]]; then
  step "ZAP baseline (web:3000, fails on any FAIL-level alert)" \
    docker run --rm --network eventfaces_default ghcr.io/zaproxy/zaproxy:stable \
      zap-baseline.py -t http://web:3000 -j
fi

echo
echo "================ summary ================"
printf '%s\n' "${RESULTS[@]}"
! printf '%s\n' "${RESULTS[@]}" | grep -q '^FAIL'
