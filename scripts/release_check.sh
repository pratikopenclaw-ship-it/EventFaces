#!/usr/bin/env bash
# Each condition is passed to `check` in single quotes and evaluated there (so the report can
# print it as a PASS/FAIL line); shellcheck can't see that, hence:
# shellcheck disable=SC2016,SC2034
# Post-deploy smoke check against a running site (read-only: GET requests and one rejected
# POST; no accounts, no data). Used by scripts/deploy.sh; run it by hand after any change.
#   scripts/release_check.sh https://photos.example.org [expected-version]
#   scripts/release_check.sh http://localhost:3000 dev          # local stack (TLS/HSTS skipped)
# Options (env): ERRORS_URL=https://errors.photos.example.org  (GlitchTip health is checked)
#                EXPECT_APP_LINKS=1  (the iOS Universal Links file must be served)
set -uo pipefail

BASE="${1:?usage: release_check.sh <base-url> [expected-version]}"
BASE="${BASE%/}"
EXPECT_VERSION="${2:-}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }
fetch() { # fetch <path> <name>: body to $TMP/<name>, headers to $TMP/<name>.h, prints status
  local code
  code=$(curl -sS -m 20 -o "$TMP/$2" -D "$TMP/$2.h" -w '%{http_code}' "$BASE$1" 2>/dev/null) || code=000
  echo "$code"
}
header() { grep -i "^$2:" "$TMP/$1.h" | tail -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ //'; }
https=0; [[ "$BASE" == https://* ]] && https=1

# 1. Health and version
# Right after a deploy the web proxy may still hold connections to the replaced API
# container: give it up to a minute before judging.
for _ in $(seq 1 12); do
  status=$(fetch /api/health health)
  [ "$status" = 200 ] && break
  sleep 5
done
check "API health answers 200 ($status)" '[ "$status" = 200 ]'
version=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["version"] if d.get("status")=="ok" else "")' "$TMP/health" 2>/dev/null)
check "health reports a version (${version:-none})" '[ -n "$version" ]'
if [ -n "$EXPECT_VERSION" ]; then
  check "deployed version is $EXPECT_VERSION" '[ "$version" = "$EXPECT_VERSION" ]'
fi
check "health shows nothing else" 'python3 -c "import json,sys; sys.exit(set(json.load(open(sys.argv[1])))!={\"status\",\"version\"})" "$TMP/health"'

# 2. TLS
if [ "$https" = 1 ]; then
  host="${BASE#https://}"; host="${host%%/*}"
  end=$(echo | openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  days=$(python3 -c 'import sys,datetime as d; e=d.datetime.strptime(sys.argv[1],"%b %d %H:%M:%S %Y %Z"); print((e-d.datetime.utcnow()).days)' "$end" 2>/dev/null || echo -1)
  check "TLS certificate valid for more than 14 days ($days)" '[ "$days" -gt 14 ]'
  plain=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "http://$host/" 2>/dev/null) || plain=000
  check "plain HTTP redirects to HTTPS ($plain)" '[ "$plain" = 308 ] || [ "$plain" = 301 ]'
fi

# 3. Security headers on a page
status=$(fetch / home)
check "home page answers 200" '[ "$status" = 200 ]'
csp=$(header home content-security-policy)
check "CSP with a per-request nonce" '[[ "$csp" == *"nonce-"* && "$csp" == *"strict-dynamic"* ]]'
check "CSP connect-src stays first-party" '[[ "$csp" == *"connect-src '"'"'self'"'"'"* && "$csp" != *"googleapis"* ]]'
check "CSP frame-ancestors none" '[[ "$csp" == *"frame-ancestors '"'"'none'"'"'"* ]]'
check "X-Frame-Options DENY" '[ "$(header home x-frame-options)" = DENY ]'
check "X-Content-Type-Options nosniff" '[ "$(header home x-content-type-options)" = nosniff ]'
check "no X-Powered-By" '[ -z "$(header home x-powered-by)" ]'
if [ "$https" = 1 ]; then
  check "HSTS" '[[ "$(header home strict-transport-security)" == *"max-age="* ]]'
fi

# 4. Cookies
status=$(fetch /api/auth/csrf csrf)
cookie=$(grep -i '^set-cookie: ef_csrf=' "$TMP/csrf.h" | tr -d '\r' | tr '[:upper:]' '[:lower:]')
check "CSRF cookie is set" '[ -n "$cookie" ]'
check "CSRF cookie is SameSite" '[[ "$cookie" == *"samesite="* ]]'
if [ "$https" = 1 ]; then
  check "CSRF cookie is Secure" '[[ "$cookie" == *"; secure"* ]]'
fi

# 5. Legal pages and documents: served, versioned, no unfilled [placeholder]
for doc in terms organizer-terms privacy imprint; do
  status=$(fetch "/$doc" "page-$doc")
  check "/$doc page answers 200" '[ "$status" = 200 ]'
  status=$(fetch "/api/legal/$doc" "legal-$doc")
  check "legal document $doc is complete" '[ "$status" = 200 ] && python3 - "$TMP/legal-$doc" <<PY
import json, re, sys
d = json.load(open(sys.argv[1]))
text = json.dumps(d, ensure_ascii=False)
sys.exit(not d.get("version") or bool(re.search(r"\[[a-z]+(?: [a-z]+)*\]", text)))
PY'
done

# 6. Production surface: no API docs, error tunnel only for our pages, app links
for path in /api/docs /api/openapi.json /api/redoc; do
  status=$(fetch "$path" docs)
  check "$path is not served ($status)" '[ "$status" = 404 ]'
done
tunnel=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -H 'Sec-Fetch-Site: cross-site' --data '{"message":"release check"}' "$BASE/monitoring" 2>/dev/null) || tunnel=000
check "error tunnel refuses other sites ($tunnel)" '[ "$tunnel" = 403 ]'
status=$(fetch /.well-known/apple-app-site-association aasa)
if [ "${EXPECT_APP_LINKS:-0}" = 1 ]; then
  check "Universal Links file is JSON" '[ "$status" = 200 ] && [[ "$(header aasa content-type)" == application/json* ]] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$TMP/aasa"'
else
  check "Universal Links file absent or JSON ($status)" '[ "$status" = 404 ] || [[ "$(header aasa content-type)" == application/json* ]]'
fi

# 7. Error tracking
if [ -n "${ERRORS_URL:-}" ]; then
  status=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "${ERRORS_URL%/}/_health/" 2>/dev/null) || status=000
  check "GlitchTip is up ($status)" '[ "$status" = 200 ]'
fi

echo
if [ "$failures" -gt 0 ]; then
  echo "release check: $failures problem(s)"
  exit 1
fi
echo "release check: OK"
