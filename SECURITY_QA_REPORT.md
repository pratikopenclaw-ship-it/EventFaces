# EventFaces — Security & QA Report

Scope: full security audit and QA of the EventFaces stack (Next.js 16, FastAPI, Postgres 16 + pgvector,
InsightFace, Celery/Redis, S3-compatible storage, Google Drive import). All testing ran against the local
docker-compose stack with synthetic test data only; no real services, accounts or user data were touched
(Google Drive is mocked; email goes to Mailpit).

Method: rounds of **Audit → Fix → Verify → Re-audit**. Every fix has a regression test that fails on the old
code and passes on the new code (verified by re-running the test against the reverted code where noted).

Severity scale: **Critical** (remote compromise / cross-tenant data or biometric exposure), **High** (auth
bypass, exploitable vuln in reachable code, privacy guarantee broken), **Medium** (defence-in-depth gap with a
plausible abuse path), **Low** (hardening, minor info leak), **Info** (no action / tracking).

## Final gate (Phase D), 2026-09-30

| Gate | Result | Evidence |
|---|---|---|
| Zero open Critical/High | **Met.** 2 High found (SEC-001, SEC-025), both fixed | Findings table |
| Medium/Low fixed or justified | **All 43 findings fixed.** SEC-039 and QA-002 were implemented after the owner's decision (2026-09-30) | Findings table |
| All tests green from a clean checkout | **Met** (delta pass: 1,202 backend tests, 35 browser tests incl. Firefox) | Fresh copy of the tree (tracked + unignored files only, `.env` from `.env.example`), new compose project with empty volumes: build, `alembic` to head (0008), **1,140 backend tests passed, 0 skipped** (1,146 after the SEC-039 tests); frontend lint, tsc, 37 vitest tests and `next build` passed; **18 Playwright tests passed** against that stack (19 with the QA-002 test, re-run against the dev stack) |
| Scanners clean or justified | **Met** | `scripts/security-scan.sh`: 18/18 steps pass; ZAP (production image) 0 FAIL, each WARN justified (Scanner results) |
| Authorization matrix passes every cell | **Met** | `tests/test_authz_matrix.py`: 67 operations × 9 actors (68 with the queued-search status endpoint) plus a completeness check against the live OpenAPI schema |
| Report complete (re-run guide, hardening checklist) | **Met** | Sections below |

### QA results (Phase C)

- **Coverage (line):** auth 97.9%, permissions 96.6%, search 97.2%, uploads 95.3%, retention 97.8%; whole app **95%** (3,327 statements).
- **Per-endpoint contracts** (`tests/test_endpoint_contracts.py`, driven by the matrix's operation table): every body endpoint returns 422 on malformed, missing and mistyped fields; every ID parameter returns 404 for unknown IDs; all 24 rate-limited endpoints return 429 once their budget is spent (the count is kept in sync with the code). Success, 401 and 403 per role: the matrix. Conflicts: concurrency, upload, invite and join tests.
- **Negative and boundary** (`tests/test_boundaries.py`, `tests/test_bounds.py`, `tests/test_upload_hardening.py`): unicode/RTL/bidi/emoji round-trips; invalid dates and timezones (SEC-036); expired verify, reset, invite, session, capture, download and removal tokens; malformed, oversized, deeply nested and non-UTF-8 bodies; NUL bytes (SEC-037); out-of-range query parameters (SEC-035); pixel bombs, polyglots and non-images (SEC-025).
- **Face-matching accuracy** (`tests/test_face_accuracy.py`: synthetic labeled set of 7 identities over 48 composite event photos, real detect → pgvector path): at the "possible" threshold (0.45), **precision 1.000, recall 0.942**; at the "best" threshold (0.55), precision 1.000, recall 0.938. Recall by face size: 40 px 0.80, 60 px 0.875, ≥80 px 1.00. The held-out impostor gets 0 matches. Edge cases (sunglasses, low light, a profile proxy, heavy blur, twins-like blends of two people) all have **0 false positives**. Limitation: probes and gallery share source photos, so the numbers are optimistic; calibrate on consented real data (README).
- **End-to-end** (`frontend/e2e`, Playwright 1.63, `docker-compose.e2e.yml`: real app, fake Drive, captured mail, test DB): admin creates event + Drive sync (mocked Drive API); sign-up → verify → join by code; invite by magic link (and link reuse can't create a second account); camera capture with a fake media stream (canvas-backed `getUserMedia`, works in every engine) → results with tiers → "This is me" feedback → single + ZIP download; too-dark selfie rejected with the right reason and only that shot retaken; guest upload → moderation → published; revoked member blocked; expired event blocked.
- **Cross-browser and mobile:** capture and gallery (`@xb`) pass in Chromium, **Firefox**, **WebKit**, **Pixel 7** (mobile Chrome) and **iPhone 14** (mobile Safari), with no horizontal overflow on the phone viewports. Firefox runs in Playwright's Linux image on the compose network (2026-09-30), because Playwright's macOS Firefox build (firefox-1543) fails to start on macOS 27 ("Could not find profile folder", even with an existing profile and outside the sandbox). The command is under "How to re-run everything"; it needed `allowedDevOrigins: ["web"]` (dev server only) and `E2E_BASE_URL`/`E2E_API_URL` overrides.
- **Accessibility:** axe WCAG 2.1 A/AA on public/auth pages, the attendee flow (events, consent, capture, results, lightbox) and all 6 organizer admin tabs: **0 serious or critical violations** after QA-001.
- **Load** (k6): see "Load test". 0 errors after SEC-038; breaking point ≈12 concurrent searches per API process (p95 ≤ 10 s target).
- **Migrations and backup/restore:** full step-down to base and back on a populated DB, partial round trips, schema-vs-model drift check (QA-003), `pg_dump`/`pg_restore` drill with content hashes, vectors, trigger and least-privilege checks.

## Findings

| ID | Sev | Title | Status |
|----|-----|-------|--------|

| SEC-001 | High | Known CVEs in parsing/auth dependencies (Pillow ×17, pillow-heif, PyJWT ×7, Starlette ×8) | Fixed |
| SEC-002 | Medium | Open redirect in post-login `?next=` (`/\evil`, `/\t/evil`) | Fixed |
| SEC-003 | Low | Test tooling (pytest, httpx) shipped in the production backend image | Fixed |
| SEC-004 | Low | `assert` used for control flow in verify-email / reset-password (stripped under `-O`) | Fixed |
| SEC-005 | Low | No backend `.dockerignore`: caches copied into images | Fixed |
| SEC-006 | Low | Frontend dev container ran as root | Fixed |
| SEC-007 | Low | Network-derived object keys used for lookups/`delete` (prototype keys) | Fixed |
| SEC-008 | Low | URL route params interpolated into API fetch paths without validation | Fixed |
| SEC-009 | Info | Capture-token payload shape not validated after JSON decode | Fixed |
| SEC-010 | Medium | Face model downloaded without integrity verification (supply chain) | Fixed |
| SEC-011 | Medium | Dev stack published Postgres (default creds), Mailpit (reset/magic links), API, S3 on all interfaces | Fixed |
| SEC-012 | Medium | Redis had no authentication (dev and production) | Fixed |
| SEC-013 | Medium | App connected to Postgres as the schema owner (no least privilege) | Fixed |
| SEC-014 | Medium | Search audit log mutable by the app; `run_search` itself rewrote audit rows | Fixed |
| SEC-015 | Low | Container images not pinned (`:latest`, floating tags) | Fixed |
| SEC-016 | Low | Excess OS attack surface in images (compiler toolchain, npm CLI): 133 + 8 HIGH CVEs | Fixed (44 no-fix residual) |
| SEC-017 | Low | Production containers without no-new-privileges / cap_drop / read-only rootfs / memory limits | Fixed |
| SEC-018 | Medium | Credentials in URL: forms without `method` fall back to GET before hydration (found by ZAP) | Fixed |
| SEC-019 | Medium | CSP allowed `'unsafe-inline'` scripts (weak XSS backstop) | Fixed |
| SEC-020 | Low | Missing COOP/CORP, `X-Powered-By` disclosure, API responses without CORP/XFO | Fixed |
| SEC-021 | Medium | Access JWTs stayed valid up to 15 min after logout / password reset | Fixed |
| SEC-022 | Medium | Refresh-token replay not detected (no session-family revocation) | Fixed |
| SEC-023 | Info | `/redoc` and `/docs/oauth2-redirect` served in dev (docs already off in prod) | Fixed |
| SEC-024 | Low | Face search had no per-event ceiling (many accounts could multiply the per-user limit) | Fixed |
| SEC-025 | High | Pixel bomb: 32 KB PNG decoded to 144 MP (~1.8 GB RSS) in the API via selfie/removal paths | Fixed |
| SEC-026 | Low | Presigned PUT URL reusable after ingest/reject → unreferenced raw objects (with EXIF/GPS) never cleaned | Fixed |
| SEC-027 | Medium | No per-user / per-event guest upload quotas (storage exhaustion) | Fixed |
| SEC-028 | Low | Download links replayable without limit (each replay streams up to 500 originals) | Fixed |
| SEC-029 | Low | Invite CSV with a >128 KB cell raised an unhandled `csv.Error` (500) | Fixed |
| SEC-030 | Low | Bearer tokens (download/invite/removal/reset) written to access logs via URLs | Fixed |
| SEC-031 | Info | CR/LF in an event name made invite/removal emails fail (header injection itself was blocked by the stdlib) | Fixed |
| SEC-032 | Low | No timeouts on Redis/DB connect/statements; S3 60 s × 5 legacy retries; Google 60 s | Fixed |
| SEC-033 | Medium | Production started happily with public dev secrets, insecure cookies, owner DB role, passwordless Redis | Fixed |
| SEC-034 | Low | Parallel joins (double-click, two tabs) raced check-then-insert → primary-key violation → 500 | Fixed |
| SEC-035 | Low | `photos?offset=` overflow → 500 (bigint out of range); `search-log?limit` unbounded/negative accepted | Fixed |
| SEC-036 | Low | Timezone-less datetimes accepted; on a reopened event they crashed the PATCH (naive vs aware compare → 500) | Fixed |
| SEC-037 | Low | NUL bytes in any text field → Postgres DataError → 500 | Fixed |
| SEC-038 | Medium | Searches held a pooled DB connection (and removal submits a row lock) during seconds of face-model CPU → ~15 concurrent searches starved the pool; unrelated endpoints 500'd | Fixed |
| SEC-039 | Medium | Unbounded queue of in-flight searches: latency grows without limit and each queued request holds its selfie bodies (≤30 MB) in memory | Fixed |
| QA-003 | Low | ORM models missing 5 migration-created indexes (incl. HNSW + a partial unique) and `events.date` mis-inferred NOT NULL: `alembic --autogenerate` would have proposed dropping them | Fixed |
| SEC-040 | Low | Base image's pip 25.0.1 (6 advisories) shipped in the production image; dev pytest 8.3.5 advisory | Fixed |
| QA-001 | Low | WCAG AA colour contrast failures (accent, secondary text, badges) and colour-only inline links | Fixed |
| QA-002 | Low | After a server-side selfie rejection the camera flow auto-retakes and resubmits with no pause; a user who keeps failing the gate exhausts their search budget in under a minute | Fixed |
| SEC-041 | High | Concurrent logins (no account needed): Argon2 at ~64 MiB each, unbounded and hashed while holding a pooled DB connection → API memory 0.7 → 2.4 GB and pool exhaustion (500s) | Fixed |
| SEC-042 | Medium | Under a 60-way burst the connection pool ran dry during auth checks and requests failed with 500 instead of degrading; pool undersized | Fixed |
| QA-004 | Low | A queued search lost in a server restart kept showing "in the queue" for up to 15 min | Fixed |
| QA-005 | Low | "One queued search per user and event" was check-then-set (not atomic across API processes) | Fixed |
| QA-006 | Low | Account page: the inline "privacy notice" link was distinguishable by colour only (axe `link-in-text-block`, 1.05:1 against the surrounding text) | Fixed |

**Totals:** 48 findings: 3 High, 15 Medium, 27 Low, 3 Info, and 0 Critical. **All 48 fixed**, each with a regression test. The delta pass (2026-09-30) added SEC-041/042 and QA-004/005 and the UX findings UX-001…UX-010 (section "Delta pass"); the theme switcher (2026-10-01) added QA-006 and UX-011.

## Finding details

### SEC-001 — Known CVEs in dependencies (High)
- **Location:** `backend/requirements.txt` (Pillow 11.3.0, pillow-heif 0.21.0, PyJWT 2.10.1, FastAPI 0.115 → Starlette 0.46.2).
- **Description:** pip-audit reported 33 advisories. Pillow and pillow-heif decode attacker-supplied images (selfies, guest uploads, Drive files); PyJWT verifies session tokens; Starlette parses every request.
- **Reproduce:** `docker compose exec api pip-audit -r requirements.txt -r requirements-ml.txt` → "Found 33 known vulnerabilities in 4 packages".
- **Fix:** FastAPI 0.141 (Starlette 1.7), Pillow 12.3, pillow-heif 1.8, PyJWT 2.15, uvicorn 0.54. Full suite green after the major Starlette upgrade.
- **Regression:** `scripts/security-scan.sh` runs pip-audit and fails on any advisory (now: "No known vulnerabilities found").

### SEC-002 — Open redirect after login (Medium)
- **Location:** `frontend/src/components/auth-card.tsx` `safeNext` (now `src/lib/links.ts`), used by `/login?next=`.
- **Description:** the check "starts with `/` but not `//`" accepted `/\evil.example`, `/\t/evil.example`, `/\n/evil.example`, which browsers normalise to `//evil.example`; `LoginForm` then did `location.href = next` → phishing redirect from a genuine login page.
- **Reproduce:** unit test resolving each value with the WHATWG URL parser: 3 of 8 payloads resolved to `https://evil.example` on the old code.
- **Fix:** resolve against a sentinel origin with `new URL()`, require the same origin, rebuild from pathname/search/hash.
- **Regression:** `frontend/src/lib/links.test.ts` (fails 3 cases on the old implementation, passes now).

### SEC-003 — Test tooling in production image (Low)
- **Location:** `backend/requirements.txt`, `backend/Dockerfile`.
- **Fix:** tooling moved to `requirements-dev.txt`, installed only with `--build-arg DEV=1` (dev compose). Production compose builds without it.
- **Regression:** `scripts/security-scan.sh` asserts `import pytest` fails in the production image.

### SEC-004 — `assert` as control flow (Low)
- **Location:** `backend/app/api/routes/auth.py` verify-email / reset-password.
- **Description:** under `python -O` the assert disappears and a missing/deleted user would raise a 500. Also now rejects soft-deleted users.
- **Fix:** explicit check returning the same generic 400.
- **Regression:** `tests/test_static_analysis.py` (ruff `S101` + bandit `B101` gates fail if reintroduced).

### SEC-005 / SEC-006 — Image hygiene (Low)
- Backend `.dockerignore` added (caches, `.env*` never enter the build context). Frontend `deps`/`dev` stages run as `node`.
- **Regression:** semgrep `missing-user` rule and trivy config scan in `scripts/security-scan.sh`.

### SEC-007 — Prototype keys from network data (Low)
- **Location:** `components/match-quality.tsx` (`REASONS[code]`, code from API), `app/events/[id]/find-photos.tsx` (422 `shot` used as an object key and in `delete`).
- **Description:** a code such as `__proto__` returns `Object.prototype` (render crash); an unvalidated `shot` drives state.
- **Fix:** `lookup()` (own properties only) and `isRejection()` validates `shot ∈ {front,left,right,any}` (`src/lib/safe.ts`).
- **Regression:** `frontend/src/lib/safe.test.ts`.
- **Scanner note:** eslint-plugin-security `detect-object-injection` is disabled in `eslint.config.mjs` with justification: its 17 hits were 15 TS-literal-union/numeric-index false positives + these 2 sites, which are now covered by tests.

### SEC-008 — URL params steering API paths (Low)
- **Location:** `/events/[id]`, `/join/[slug]`, `/invite/[token]`, `/removal/[token]`, `/admin/events/[id]`, `/removal-request?event=`.
- **Description:** values like `..%2F..%2Fme` were decoded and path-normalised into a different same-origin API request (GET only, same user — limited impact).
- **Fix:** format validation (`isUuid` / `isSlug` / `isToken`) at the page boundary → 404.
- **Regression:** `frontend/src/lib/safe.test.ts` ("URL param formats").

### SEC-009 — Capture-token payload validation (Info)
- **Location:** `backend/app/services/capture_tokens.py`. Found by mypy strict (`no-any-return`).
- **Fix:** payload must decode to a dict with matching user and event; malformed values are treated as invalid tokens.
- **Regression:** mypy strict gate in `tests/test_static_analysis.py`; behaviour covered by `test_capture_token_is_bound_to_user_and_event`.

### SEC-010 — Unverified model download (Medium)
- **Location:** backend image build (InsightFace's downloader fetched `buffalo_l.zip` with no checksum).
- **Fix:** `backend/scripts/fetch_model.py` downloads from the pinned GitHub release and verifies a pinned SHA-256 per model file; the build fails on mismatch. Only the 3 models the app loads are shipped (unused gender/age and 2D-landmark models dropped).
- **Regression:** `tests/test_fetch_model.py` (tampered archive → build aborts, nothing written).

### SEC-011 — Services exposed on all interfaces in dev (Medium)
- **Location:** `docker-compose.yml`.
- **Description:** Postgres (`eventfaces/eventfaces`) on `0.0.0.0:5432`; Mailpit (contains verification, reset and invite magic links) on `0.0.0.0:8025`; API/S3/web likewise. Anyone on the same network (café/office Wi-Fi) could read the database or take over accounts via Mailpit.
- **Fix:** Postgres is not published at all; every other port binds to `127.0.0.1`.
- **Regression:** `scripts/check_compose.py` (fails on the original file with 30 problems; passes now).

### SEC-012 — Redis without authentication (Medium)
- **Description:** Redis holds rate-limit/lockout counters, capture tokens, ZIP download tickets and the Celery broker. Unauthenticated access allows resetting lockouts, forging capture tokens and injecting tasks.
- **Fix:** `requirepass` in dev and production; all clients use `redis://:password@…`; production adds `maxmemory` + `noeviction`.
- **Regression:** `tests/test_db_privileges.py::test_redis_requires_authentication`, `scripts/check_compose.py`.

### SEC-013 — No least-privilege database role (Medium)
- **Fix:** migration `0007` creates `eventfaces_app` (LOGIN, no superuser/createdb/createrole) with DML on app tables only; no DDL, no TRUNCATE, read-only `alembic_version`; `REVOKE ALL ON SCHEMA public FROM PUBLIC`. Migrations run via `MIGRATION_DATABASE_URL` (owner). The password is set through a bound parameter (never spliced into SQL). **The entire test suite now runs as `eventfaces_app`.**
- **Regression:** `tests/test_db_privileges.py` (8 forbidden statements, role identity).

### SEC-014 — Mutable audit log (Medium)
- **Description:** brief requirement "append-only for app users". Nothing prevented UPDATE/DELETE. Adding the guard exposed that `run_search` inserted the audit row with `match_count=0` and **updated** it afterwards.
- **Fix:** `search_audit_guard` trigger: UPDATE only for anonymisation (setting `user_id`/`event_id` to NULL, as account/event deletion do); DELETE only for rows older than 30 days (retention). `AUDIT_RETENTION_DAYS` validated `>= 30`. `run_search` now writes the audit row once with its final values.
- **Regression:** `tests/test_db_privileges.py` (rewrite blocked, recent delete blocked, anonymisation and retention-age delete allowed, settings floor) + the full search suite running under the trigger.

### SEC-015 — Unpinned images (Low)
- **Fix:** every image pinned by version tag **and** digest (python 3.12.14-slim, node 22.23.3-alpine, pgvector pg16, redis 7.4.11, caddy 2.11.4, seaweedfs, mailpit).
- **Regression:** `scripts/check_compose.py` (digest required) + Dockerfile `ARG` digests.

### SEC-016 — Image attack surface (Low)
- **Description:** trivy: API image 133 HIGH (89 from `linux-libc-dev`, pulled in by the g++ needed to build InsightFace), web image 8 HIGH (all inside the npm CLI bundled in `node:alpine`).
- **Fix:** multi-stage backend build (wheels compiled in a builder; runtime has no compiler; `apt-get upgrade`); npm/npx/yarn removed from the web runtime image (the server runs `node server.js`).
- **Result:** web 8 → **0**; API 133 → **44**, all in base Debian packages with **no upstream fix** (util-linux, login, ncurses, perl-base) → accepted residual risk R-1.
- **Regression:** trivy image scan in `scripts/security-scan.sh`.

### SEC-017 — Production container hardening (Low)
- **Fix:** api/worker/beat/web: `no-new-privileges`, `cap_drop: [ALL]`, `read_only: true` with tmpfs scratch, memory limits; Caddy gets only `NET_BIND_SERVICE`; only Caddy publishes ports; uvicorn `--limit-concurrency`, `--timeout-keep-alive`; Celery `--max-tasks-per-child`. Verified the production API image serves requests and runs face detection with a read-only root filesystem as uid 10001 (writes to `/app` fail with EROFS).
- **Regression:** `scripts/check_compose.py`.

### SEC-018 — Passwords in URLs on pre-hydration submit (Medium)
- **Found by:** ZAP baseline (`10024` Sensitive Information in URL: `/login?email=…&password=ZAP`).
- **Description:** all 12 forms had no `method`; a submit before React hydrates (slow network, JS error, blocked script) is a native **GET**, putting passwords/emails/access codes into the URL, browser history, proxy and server logs.
- **Fix:** `method="post"` on every form.
- **Regression:** `frontend/src/lib/forms.test.ts` (fails with 12 offenders on the old code).

### SEC-019 — CSP allowed inline scripts (Medium)
- **Found by:** ZAP baseline (`10055` CSP: script-src unsafe-inline).
- **Fix:** per-request nonce CSP generated in `src/proxy.ts` (`src/lib/csp.ts`): `script-src 'self' 'nonce-…' 'strict-dynamic' 'wasm-unsafe-eval'` (no `'unsafe-inline'`/`'unsafe-eval'` in production), `frame-ancestors 'none'`, `object-src 'none'`, `base-uri`/`form-action 'self'`, `upgrade-insecure-requests`. Root layout forces dynamic rendering (required for nonces). Verified: fresh nonce per request and all 17 `<script>` tags carry it; browser run shows no violations.
- **Residual:** `style-src 'unsafe-inline'` kept (React `style={}` attributes cannot carry nonces) → R-2.
- **Regression:** `frontend/src/lib/csp.test.ts`.

### SEC-020 — Header hygiene (Low)
- `poweredByHeader: false`; `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` on pages; API adds CORP and `X-Frame-Options: DENY` to its existing `nosniff`/`no-store`/`Referrer-Policy`.
- **Regression:** `tests/test_auth.py::test_security_headers_on_api_responses`.

### SEC-021 — Access tokens outlived their session (Medium)
- **Found by:** manual review of `deps.get_current_user` (Phase B §1): it only verified the JWT signature/expiry.
- **Reproduced:** copy `ef_access` from a logged-in client → victim logs out (or resets the password after noticing a compromise) → `GET /api/me` with the copied cookie still returned **200** for the rest of the 15-minute lifetime.
- **Fix:** login sessions. Every login gets a `session_id`; refresh tokens carry it (migration `0008`) and rotation keeps it; the access JWT carries it as `sid`. `get_current_user` requires a live (unused, unexpired) refresh token in that session — one indexed lookup per request. Logout ends the session; reset-password / account deletion revoke all sessions; so the access token dies immediately. Tokens without a valid `sid`/`sub` UUID are rejected (also removes a latent 500 on a signed-but-malformed `sub`). Logging out one device leaves the others alive.
- **Regression:** `tests/test_sessions.py::test_access_token_dies_on_logout`, `::test_access_token_dies_on_password_reset`, `::test_logout_only_ends_that_session`, `::test_forged_and_malformed_access_tokens_are_rejected` (alg=none, wrong key, no/unknown sid, expired, wrong type, bad sub, garbage).

### SEC-022 — Refresh-token replay not detected (Medium)
- **Reproduced:** copy `ef_refresh` → victim refreshes (rotation) → attacker presents the copied token: 401, but nothing else happens; conversely if the attacker refreshes first they get a full session and the victim just sees a logout. No theft signal, no revocation.
- **Fix:** `tokens.rotate_refresh_token`: presenting an already-rotated token later than `REFRESH_REUSE_GRACE_SECONDS` (default 20 s, bounded 0–120) revokes the **whole session** (thief and victim both lose it; the victim logs in again, the thief cannot). Within the grace window it is treated as a benign concurrent refresh from another tab (plain 401, session kept) — same user-visible behaviour as before for that race.
- **Tradeoff:** a copied refresh token replayed within 20 s of a legitimate rotation is only refused, not escalated. Accepted (R-5).
- **Regression:** `tests/test_sessions.py::test_refresh_token_replay_revokes_the_session`, `::test_concurrent_refresh_within_grace_does_not_log_out`, `::test_refresh_keeps_the_session_alive`.

### SEC-023 — Extra docs endpoints in dev (Info)
- `redoc_url=None`, `swagger_ui_oauth2_redirect_url=None`; `/docs` + `/openapi.json` exist only when `ENVIRONMENT=development` (production already disabled them).

### Phase B §2 — Authorization (no findings)
- `tests/test_authz_matrix.py`: **67 operations × 9 actors = 603 cells + completeness check** (fails if any OpenAPI operation lacks an entry). Actors: anonymous, unverified, attendee-not-member, attendee-member, revoked, expired, organizer of another event, organizer of this event, super_admin. Allowed actors must not get 401/403 (inputs are valid so business rules don't mask authorization); denied actors must get exactly 401 (anonymous) or 403; no cell may 5xx.
- `tests/test_idor.py`: 16 cross-event ID substitutions (photos, variants, uploads, members, invites, reports, removal requests) by members, organizers and super_admin through event A's routes → **404 identical to a random UUID** (no existence oracle) and a DB snapshot of event B proves no side effect. Plus foreign-photo downloads/feedback, download links bound to their user, and listings (pagination/sort/filter params) never containing event-B IDs. **Mutation-checked:** removing the event check in `moderation._locked_photo` makes 3 cases fail.
- `tests/test_revocation_and_mass_assignment.py`: revoke / back-to-pending / membership expiry / event access end / API revoke / photo removal / account deletion / organizer demotion all take effect on the next request with the same session and on already-issued signed download links; signup, event PATCH, member PATCH and join bodies cannot set role, verification, id, slug, access code, ownership or retention fields; an organizer cannot revoke a fellow organizer.

### SEC-024 — No per-event search ceiling (Low)
- **Found by:** Phase B §3 review of search rate limits: per user (10/10 min) and per IP (30/10 min) only. An attacker with several verified accounts joined to one event (code-mode events need only the code) could multiply the per-user budget to scrape the event with arbitrary face images.
- **Fix:** `SEARCH_EVENT_RATE_LIMIT` (default 600 per 10 min per event, above what one CPU worker can process, so legitimate peaks aren't throttled). It's counted only after consent, capture-token and upload-policy checks pass, so invalid requests from one member can't exhaust the event's budget for everyone.
- **Regression:** `tests/test_search_abuse.py::test_search_has_a_per_event_ceiling` (fails on old code), `::test_rejected_requests_do_not_burn_the_event_budget`.
- **Also verified (no finding):** selfies/embeddings absent from logs at DEBUG (`::test_search_logs_contain_no_selfie_or_embedding`), from Redis (`::test_search_leaves_nothing_biometric_in_redis`), and the schema has exactly one vector column (`faces.embedding`) and no blob columns (`::test_only_the_faces_table_stores_vectors_and_nothing_stores_blobs`); existing tests cover storage, temp files, single-use/bound/expiring capture tokens, the upload-policy switch and the server-side quality gate. Removal-request matching (the only anonymous face matching) never returns matches to the requester.

### SEC-025 — Decompression bomb below Pillow's hard limit (High)
- **Found by:** Phase B §4 review of `imaging.load_image`: `MAX_IMAGE_PIXELS=120 MP`, but Pillow only *raises* above 2× that; between 1× and 2× it just warns and decodes. The non-RGB branch also made an extra RGBA copy.
- **Reproduced:** `Image.new("1",(12000,12000)).save(png)` → **32 KB** file; `load_image` decoded it in 1.7 s with **peak RSS 1821 MB** (measured in the API container). Reachable in the **API process** via selfie search (file mode) and via `POST /api/removal-requests/{token}/submit`, for which anyone can get a token by entering their own email. The prod API has 2 workers in a 3 GB container, so 2–3 concurrent requests would OOM-kill it (≈56,000× amplification).
- **Fix:** the pixel count is checked from the header (`Image.open` is lazy) *before* decoding: `IMAGE_MAX_PIXELS` (120 MP, event photos) and `SELFIE_MAX_PIXELS` (50 MP, selfies and removal references). Non-alpha modes now convert straight to RGB (no RGBA intermediate); 16-bit is scaled correctly.
- **Regression:** `tests/test_upload_hardening.py::test_pixel_bomb_below_pillows_hard_limit_is_rejected_before_decoding` (fails on old code: decodes), `::test_selfies_have_a_lower_pixel_limit`, `::test_photo_limit_matches_setting`, `tests/test_search_abuse.py::test_selfie_pixel_bomb_is_refused_without_decoding` (API, <1 s).
- **Also verified (no finding), same file:** 200-frame APNG → first frame only, <2 s; JPEG+HTML+ZIP polyglot → payload gone after re-encode; SVG/HTML/GIF/WebP/PDF/nulls/empty/fake-JPEG → clean `UnsupportedImage`; all pixel modes → RGB; download filenames with traversal, `\x00`, CRLF header injection, quotes, RTL override and 500 chars → inert ASCII names. Existing tests cover magic bytes vs declared type, EXIF/GPS stripping, presigned URL locked to size and type, single-use complete, and owner-only.

### SEC-026 — Presigned URL outlives its upload (Low)
- **Reproduced:** complete an upload (ingest deletes the raw object) → PUT again to the same URL within its 10-min life → the raw object, with the original EXIF/GPS, exists again with no DB row referencing it, and nothing ever deleted it.
- **Fix:** the hourly `cleanup_abandoned_uploads` also sweeps `events/<id>/uploads/` objects that no photo row references and that are older than URL lifetime + 1 h (in-flight uploads are referenced, so they're kept). `delete_keys` now batches at S3's 1000-key limit. S3 conditional `If-None-Match` writes weren't used: they need signing support and a SeaweedFS/R2 feature check, and the sweep covers every backend.
- **Regression:** `tests/test_guest_uploads.py::test_reused_presigned_url_cannot_leave_an_orphan_object`, `::test_cleanup_keeps_uploads_in_flight`.

### SEC-027 — No upload quotas (Medium)
- **Found by:** Phase B §4 checklist ("per-user and per-event upload quotas"): only a rate limit existed (60/h/user), so one member could add ~1,440 × 25 MB ≈ 36 GB/day and a group far more.
- **Fix:** `GUEST_UPLOAD_MAX_PER_USER` (200 live uploads per user per event) and `GUEST_UPLOAD_MAX_PER_EVENT` (5000) → 409 with a clear message. Rejected and removed uploads don't count. The check runs under a row lock on the event, so concurrent starts can't overshoot.
- **Regression:** `tests/test_guest_uploads.py::test_per_user_upload_quota`, `::test_per_event_upload_quota`, `::test_rejected_and_removed_uploads_free_the_quota`.

### SEC-028 — Unlimited download-link replay (Low)
- **Reproduced:** one ZIP link redeemed 125× in a row → 125 × 200 (each up to `ZIP_MAX_PHOTOS`=500 originals streamed). Link creation was limited (60/10 min) but redemption wasn't.
- **Fix:** redemption limited to 120 per user per 10 min. Links stay reusable within their 120 s life for retries and resumes.
- **Regression:** `tests/test_idor.py::test_download_link_replay_is_rate_limited`.
- **Also verified (no finding):** ZIP entry names go through `safe_filename` (traversal-free, see SEC-025 tests) and are deduplicated; per-file authorization is re-checked at redemption (`viewable_photos` for every ID, all-or-nothing); count cap is 500; storage URLs are never exposed (bytes are proxied); `Cache-Control: private, no-store`.

### SEC-029 — CSV parser crash (Low)
- **Reproduced:** `parse_emails("a"*200_000)` → `_csv.Error: field larger than field limit (131072)`, unhandled in `POST /api/events/{id}/invites` → 500.
- **Fix:** `csv.Error` → 422 with a plain message. The body is already capped at 500k chars and 2000 invites per upload.
- **Regression:** `tests/test_injection.py::test_malformed_invite_csv_is_a_clean_422` (huge cell, unterminated quote, valid-then-huge).
- **CSV formula injection:** not applicable. CSV is input only, and there is no CSV/XLSX export anywhere. Formula-looking and markup cells fail email validation and are only echoed back as React text (`::test_formula_and_markup_cells_are_not_invited`).

### SEC-030 — Tokens in access logs (Low)
- **Found by:** review of URL-borne secrets: `/api/downloads/{token}`, `/api/invites/{token}`, `/api/removal-requests/{token}[/submit]`, `/invite/{token}`, `/removal/{token}`, `?token=` (verify/reset). Uvicorn's access log records full paths, so anyone with log access could redeem an invite (register as the invitee) or act on a removal request.
- **Fix:** `app/core/logging.RedactTokens` filter on `uvicorn.access` (installed by `create_app`) replaces those segments with `[redacted]`. Non-secret paths are untouched. The production Caddyfile has no access log, and the checklist says to keep it that way or apply the same redaction.
- **Regression:** `tests/test_injection.py::test_access_log_redacts_bearer_tokens_in_urls` (6 URL shapes), `::test_uvicorn_access_args_are_redacted_too`, `::test_redaction_filter_is_installed_on_uvicorn_access`, `::test_non_secret_paths_are_untouched`.

### SEC-031 — Mail subject robustness (Info)
- An organizer-chosen event name containing CR/LF was passed to the email `Subject`. Python's `EmailMessage` refused it (no injection possible), but the background send then failed silently.
- **Fix:** `email.build_message` flattens control characters in `Subject`/`To`.
- **Regression:** `tests/test_injection.py::test_mail_subject_cannot_inject_headers`.

### Phase B §6 — other injection checks (no findings)
- **SQL/vector:** no string-built SQL anywhere (`grep text(f|execute(f|.format(` is empty). The embedding is bound as a parameter, and `search_faces` takes `event_id` as a required keyword.
- **Command/template/deserialization:** no `subprocess`/`os.system`/`eval`/`exec`/`pickle`/`yaml.load`/Jinja in `app/`. Celery `accept_content=["json"]`, and `result_serializer` is now pinned to json too (`::test_celery_accepts_json_only`).
- **Redis:** keys are built from UUIDs and length-bounded emails; redis-py sends them as binary-safe bulk strings, so there's no command injection.
- **SSRF:** the Drive input is reduced to `[A-Za-z0-9_-]{10,200}` before use, and the only outbound calls go to the Google API client with that ID (`::test_drive_input_can_only_yield_a_plain_id`: metadata IP, file://, gopher://, traversal, encoded slashes).
- **XSS:** no `dangerouslySetInnerHTML`/`innerHTML`/`new Function` in `frontend/src`. The nonce CSP is from SEC-019. Emails are text/plain.
- **Open redirect:** SEC-002. The backend issues no redirects.
- **Log injection:** app logs only IDs and the retention report dict.

### SEC-032 — Unbounded waits on dependencies (Low)
- **Found by:** Phase B §7 review of client construction: Redis had no socket timeout at all (rate limiting runs on every request, so one hung Redis would stall every API thread); psycopg had no connect timeout and Postgres no statement timeout; boto3 defaults were 60 s connect and read with legacy 5 retries (~5 min worst case per call); the Google client used 60 s. SMTP already had 10 s.
- **Reproduced:** `tests/test_timeouts.py::test_redis_calls_time_out` runs a local tarpit socket (accepts, never answers). The old client blocks forever; the new one raises `TimeoutError` in about 5 s.
- **Fix:** Redis `socket_timeout=5`, `socket_connect_timeout=3`, health checks. DB `connect_timeout=5`, `pool_timeout=10`, `statement_timeout` = `DB_STATEMENT_TIMEOUT_MS` (60 s, sized for worker batch jobs). S3 connect 5 s, read 30 s, standard retry mode with 3 retries. Google transport 30 s.
- **Regression:** `tests/test_timeouts.py` (7 tests, including a real `pg_sleep` cut off by `statement_timeout`).

### SEC-033 — No fail-closed production configuration (Medium)
- **Found by:** Phase B §7 review of `Settings`: nothing stopped `ENVIRONMENT=production` from running with the `.env.example` values, which are public in the repo: the JWT secret (anyone could mint sessions before SEC-021; after it, a live `sid` is still needed), the download-token secret, `COOKIE_SECURE=false`, the DB owner role or dev password, Redis without a password, the dev S3 key, or Mailpit as SMTP.
- **Reproduced:** `Settings(environment="production", jwt_secret="change-me-dev-only-…", cookie_secure=False, …)` loaded without error (12 insecure variants in the regression test all loaded).
- **Fix:** `Settings._refuse_insecure_production` (a pydantic model validator) lists every problem and refuses to start: dev-prefixed or low-entropy (<100 bits) secrets, identical JWT/download secrets, insecure cookies, non-https frontend, DB role not `eventfaces_app` or a public password, Redis without a private password, public S3 secret, Mailpit host. README deployment steps updated (they still described the pre-SEC-013 single DB user).
- **Regression:** `tests/test_infra_config.py::test_production_refuses_insecure_settings` (12 cases fail on old code), `::test_valid_production_settings_load`, `::test_dev_defaults_still_load_outside_production`.
- **Also verified (no finding), same file:** `/api/docs`, `/api/openapi.json`, `/redoc` and `/docs` all 404 in production. The API sends no CORS grants to foreign origins (there's no CORS middleware; the browser reaches it same-origin through the Next rewrite). The bucket CORS written by `cli init-storage` allows PUT only, from the frontend origin only, and a foreign-origin preflight gets no ACAO. Anonymous GET, list and PUT against the bucket all get 403.

### SEC-034 — Join race (Low)
- **Reproduced:** 8 parallel `POST /api/join` for the same user (barrier-synchronized) with the membership lookup widened to 300 ms → `UniqueViolation event_members_pkey` → 500. Unwidened, the window is milliseconds, but a double-click or two tabs can hit it.
- **Fix:** `INSERT … ON CONFLICT DO NOTHING`, then `SELECT … FOR UPDATE` on the row and the same rules (a revoked member stays revoked; pending becomes approved).
- **Regression:** `tests/test_concurrency.py::test_parallel_join_creates_one_membership`, which widens the window deterministically in the test (not in app code) and fails on the old code every time.
- **Also verified (no finding), same file, every call barrier-started ×8:** invite accept (one membership; already serialized by the invite-row lock), invite register (one account), password-reset token (exactly one 200), one refresh cookie from 8 "tabs" (one winner, session survives), upload starts versus quota (exactly the quota), upload complete (exactly one 200), mixed approve/reject and revoke/approve by organizers and admins (no 5xx, never half-applied), sync start (runs = 202s), and revoke racing downloads (the link is dead afterwards).

### SEC-035 — Unbounded query parameters (Low)
- **Reproduced:** `GET /api/events/{id}/photos?offset=99999999999999999999999` → `NumericValueOutOfRange: bigint out of range` → 500. `GET …/search-log?limit=-1|0|100000000` accepted.
- **Fix:** `offset ≤ 1,000,000`; `search-log` `limit` must be 1–1000. Both return 422 otherwise.
- **Regression:** `tests/test_bounds.py::test_out_of_range_query_params_are_422` (11 cases), `::test_malformed_path_ids_are_rejected_not_crashing` (non-UUIDs, `%00`, encoded traversal, 5000-character IDs on 4 routes).

### Phase B §8 — GDPR (no findings)
- Existing: delete-my-data erases memberships, grants, uploads (files and faces), invites, removal requests and tokens, and anonymizes the audit and feedback; consent withdrawal deletes grants and anonymizes feedback; event expiry deletes faces, grants and invites (optionally photos) and stops late index jobs from recreating faces; retention purges audit and quality rows, expired grants, stale unverified accounts and old tokens; removal requests are end-to-end, organizer-scoped, and indistinguishable for unknown events.
- Added (`tests/test_gdpr.py`): an organizer can erase their account (invites, resolved reports and sync runs keep the history without the person; the event survives); removal requests are purged by status and age while still-open ones are kept; deleting an event leaves **no row in any `event_id` table** (checked generically via `information_schema`).
- **Residual:** no self-service data export (Art. 15/20), since adding it would be a feature → R-6.

### SEC-036 — Ambiguous (timezone-less) timestamps (Low)
- **Found by:** Phase C boundary testing (`tests/test_boundaries.py`).
- **Reproduced:** `PATCH /api/events/{id}` with `{"access_expires_at": "2030-01-01T00:00:00"}` on an event whose retention had run → `TypeError: can't compare offset-naive and offset-aware datetimes` → 500. Elsewhere the naive value was stored as the DB session's timezone and echoed back without an offset, and `+14:00` inputs were echoed un-normalized.
- **Fix:** `UtcDatetime` (pydantic `AwareDatetime` normalized to UTC) for `access_expires_at` (create and update) and member `expires_at`. Naive values → 422. The frontend already sends `toISOString()` (UTC), so users see no difference.
- **Regression:** `::test_naive_expiry_on_reopened_event_is_rejected_not_500` (500 on old code), `::test_member_expiry_requires_timezone`, `::test_timezone_offsets_are_normalised`, `::test_event_field_boundaries` (naive → 422; `+14:00` and `Z` accepted; year 10000 rejected).

### SEC-037 — NUL bytes crash writes (Low)
- **Reproduced:** `POST /api/events {"name": "nul\u0000byte"}` → `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes` → 500. The same applies to any free-text field (descriptions, removal messages, upload filenames, report details).
- **Fix:** a global `sqlalchemy.exc.DataError` handler in `create_app` → 422 with a generic message. It logs only the error class, never the value. It also catches any other value the database can't store (numeric overflow; SEC-035 already bounds the known ones).
- **Regression:** `tests/test_boundaries.py::test_null_bytes_in_text_fields_do_not_crash` (500 on old code).
- **Also verified (no finding), same file:** 7 unicode/RTL/bidi-override/ZWJ-emoji/combining/astral/CJK strings round-trip exactly, and slugs stay ASCII; name and description length limits; invalid calendar dates; expired verification, reset, invite and session tokens (the old password still works after a failed reset); 2 MB and 1 MB fields → 4xx; 100,000-deep nested JSON and invalid UTF-8 → 4xx, not 500. Oversized requests are also capped at 12 MB by Caddy in production (`request_body max_size`).

### SEC-038 — Face work starved the DB connection pool (Medium)
- **Found by:** the k6 load test (Phase C). 2 × 500 on `POST /capture-token` with `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached`.
- **Root cause:** the search route's auth dependencies open a transaction, which keeps its pooled connection checked out while `run_search` waits seconds for the (serialized) face model. About 15 concurrent searches held all 15 connections, so every other endpoint (login, downloads, capture-token) timed out. A few accounts could take the whole API down. Removal-request submit was worse: it held a `SELECT … FOR UPDATE` row lock and a connection during embedding.
- **Fix:** the search route commits (ending the read-only auth transaction) before the CPU phase; `run_search` does all face analysis before its first query, so SQLAlchemy checks out a new connection only when it needs one. Removal submit now validates the link, releases lock and connection, computes the embedding (`removal.reference_embedding`), then re-locks and re-checks that the request is still open before writing.
- **Regression:** `tests/test_pool_starvation.py::test_search_holds_no_db_connection_during_face_analysis` and `::test_removal_submit_holds_no_db_connection_during_face_analysis` (both fail on old code: a connection was checked out while the model ran), `::test_removal_submit_twice_concurrently_submits_once` (releasing the lock doesn't allow a double submit). Re-run under load: 0 errors, 0 tracebacks, download p95 4.6 s → 0.96 s.

### SEC-039 — Unbounded search queue (Medium)
- **Found by:** load test. Searches are CPU-bound and the face model is serialized per process (≈0.9/s), so latency grew with every concurrent search (p95 27 s at 31–45 users, still climbing), and every queued request held its selfie set (up to 3 × 10 MB) in memory. Rate limits bound each abuser, but not total load.
- **Fix (owner chose the recommended option):** `app/core/face_slots.py`, a per-process cap on face work shared by search and removal submit.
  - The request ends its DB transaction (SEC-038), then takes a slot before reading its body, spending search budget or burning its capture token.
  - It waits up to `SEARCH_QUEUE_WAIT_SECONDS` (5 s) for a slot; if none frees up, it gets **503 + `Retry-After: 10`** with "Lots of people are searching right now. Please try again in a few seconds." The frontend shows that message and re-arms the camera.
  - `SEARCH_MAX_CONCURRENT` defaults to **6**, sized as throughput × acceptable wait rather than by CPU count, because the model is serialized. A first attempt at 2× cores (20 on the test machine) still let admitted searches wait about 28 s.
  - Queued-request memory is now at most cap × 30 MB per process.
- **Regression:** `tests/test_search_capacity.py`.
  - `::test_search_beyond_capacity_is_503_fast_without_reading_the_body`: < 3 s, `Retry-After`, the body is never read, and the busy response doesn't cost search budget.
  - `::test_a_request_waits_briefly_for_a_slot_before_giving_up` and `::test_slots_are_released_after_success_and_rejection`.
  - `::test_removal_submit_shares_the_cap`.
  - `::test_waiting_for_a_slot_holds_no_db_connection` (the queue must not reintroduce SEC-038).
  - Under load (k6, below): admitted searches p95 **12.0 s at every concurrency level** (was 27 s and rising); busy answers in about 5.1 s; downloads and uploads faster; 0 errors, 0 tracebacks.

### QA-003 — Model/migration drift (Low)
- **Found by:** `tests/test_migrations.py::test_migrated_schema_matches_the_models` (alembic `compare_metadata` against a freshly migrated database).
- **Description:** `ix_faces_embedding_hnsw` (the vector index), the partial unique `uq_match_feedback_user_photo` (one verdict per user and photo), and `ix_search_audit_created_at`, `ix_search_grants_expires_at` and `ix_selfie_quality_created_at` (used by retention) existed only in migrations. Anyone generating a migration with `--autogenerate` would have been offered `DROP INDEX` for all five. Separately, `events.date` came out NOT NULL in the metadata because the attribute name `date` shadows the type in its own `Mapped[date | None]` annotation.
- **Fix:** indexes declared on the models (`__table_args__` / `index=True`); `nullable=True` spelled out, with a comment. No schema change, so no migration.
- **Regression:** the same test (6 diffs on old code, 0 now).

### Migrations & backup/restore (no findings)
- `tests/test_migrations.py`, in a scratch database with a row in every table:
  - Step down one revision at a time from head (0008) to an empty schema, checking at each step that every surviving table keeps its rows; then upgrade back to head.
  - 1-, 2- and 3-step round trips keep `users`/`events`/`photos`/`faces`/`event_members` byte-identical and every surviving table's row count.
  - The migrated schema leaves `eventfaces_app` non-superuser, unable to write `alembic_version`, with the audit trigger in place.
- `scripts/backup_restore_drill.sh`: `pg_dump -Fc` (58 KB for the sample) → `pg_restore` into a new database. All 14 tables match by count and content hash, vector nearest-neighbour results match, the audit trigger, HNSW index and alembic version are present, the app role can connect and write, and the audit log is still append-only. **Note for operators:** backups contain face embeddings (biometric data). Encrypt them, restrict access, and expire them in line with the retention table (hardening checklist).

### SEC-040 — Vulnerable pip in images (Low)
- **Found by:** `scripts/security-scan.sh` re-run (pip-audit): pip 25.0.1 from `python:3.12-slim` (PYSEC-2026-196/-1795/-1796/-2875/-2876/-3721) in both images, and pytest 8.3.5 (PYSEC-2026-1845, dev image only).
- **Fix:** builder and runtime upgrade to `pip==26.2.*`; production images (`DEV=0`) **uninstall pip entirely** once installation finishes; pytest 9.0 / pytest-cov 7. Full suite re-run green.
- **Regression:** `scripts/security-scan.sh` → pip-audit (0 advisories), and "production API image ships without test tooling or pip" (asserts `python -m pip` fails in the prod image).

### QA-001 — Accessibility: colour contrast (Low)
- **Found by:** axe (`frontend/e2e/a11y.spec.ts`, WCAG 2.1 A/AA, serious and critical only) on public, attendee and organizer screens.
- **Fix:** accent `#e0531f` → `#b53c0a` (≥4.8:1 on paper, canvas and mist; white on accent 5.8:1). Secondary text `text-ink/45–65` → `/70` (≥5.8:1). Good/bad badge text darkened (≥5.9:1). Links inside running text are underlined (`link-in-text-block`). A visual tint change only; no behaviour change.
- **Regression:** `e2e/a11y.spec.ts` (3 tests, 0 serious or critical violations).
- **Not a finding:** a `color-contrast` hit on the admin Photos tab (tracked as QA-001b) was axe sampling the Sync button mid-fade from its disabled 50% opacity. The audit helper now waits for CSS transitions (`document.getAnimations()`) before scanning.

### QA-002 — Auto-resubmit loop after a selfie rejection (Low)
- **Found by:** e2e debugging. When the server rejects a frame that the browser's live guidance accepted (e.g. blur or low detection confidence, which the browser doesn't measure), the guided capture retook and resubmitted automatically. Within about 10 cycles the user hit the 10-per-10-minutes search limit and was locked out for 10 minutes.
- **Fix (owner chose the recommended option), `guided-capture.tsx`:**
  - The first server rejection auto-retakes as before.
  - A second rejection in a row **pauses**: the camera stays off, auto-capture and the manual shutter are disabled (the detection loop is guarded so it can't capture the frozen last frame), and the screen shows the reason, four practical tips and **Try again**.
  - A success resets the count. After a manual "Try again", any further rejection pauses again, so it never loops.
- **Regression:** `frontend/e2e/retry-loop.spec.ts`. A blurry front frame (passes the browser's check, fails the server's sharpness gate) produces exactly 2 search submits, then the paused state with the reason and "Try again", and no third submit over 8 s. "Try again" re-arms at the rejected shot. **Mutation-checked:** with the pause disabled (`AUTO_RETRIES_AFTER_REJECTION = 99`) the test fails.

## Delta pass before deployment (2026-09-30)

Scope: everything changed since the audit (queued searches, the SEC-039/QA-002 fixes, Firefox harness), plus a UX pass, queued-search stress tests, a face-engine interface and a deployment guide (`DEPLOYMENT.md`).

### SEC-041 — Password hashing could take the API down (High)
- **Found by:** the 10× burst load test (`loadtest/queue-burst.js`: 60 users logging in and searching at the same instant against one API process).
- **Reproduced:** API memory 0.7 → **2.4 GB** and `QueuePool limit … reached` tracebacks. Argon2 (argon2-cffi defaults, deliberately memory-hard at ~64 MiB per hash) ran unbounded in up to 40 threadpool threads, and `login` hashed while its pooled DB connection was still checked out, so unrelated requests 500'd. **No account is needed:** ~40 wrong-password logins from one IP fit within the rate limits, and the production API is capped at 3 GB.
- **Fix:**
  - `security.hash_password`/`verify_password` take one of `PASSWORD_HASH_MAX_CONCURRENT` (4) slots per process, waiting up to `PASSWORD_HASH_WAIT_SECONDS` (3), else `HashingBusy` → **503 + Retry-After**. That bounds hashing memory at about 256 MB per process and covers every caller.
  - Login, sign-up, account deletion and invite registration release the DB connection before hashing.
  - Reset-password now validates the link read-only (`tokens.find_valid_token`), hashes with no connection or lock held, then consumes the token under its row lock.
  - Argon2 parameters are unchanged (no weakening).
- **Regression:** `tests/test_password_hashing.py`: no pooled connection held during hashing for login (valid, wrong and unknown email), sign-up, reset, delete-me and invite registration; with a cap of 2 and 6 parallel logins, peak concurrency ≤ 2 and the excess gets 503 with Retry-After, never 500. Re-run burst: memory peak 1.4 GB (models loaded), 0 tracebacks.

### SEC-042 — Pool exhaustion surfaced as 500 (Medium)
- **Found by:** the same burst after SEC-041. With the CPU saturated by face analysis, even short auth queries waited past the 10 s pool timeout (default pool 5 + 10).
- **Fix:** `sqlalchemy.exc.TimeoutError` → **503 + Retry-After** ("the service is very busy"), logged without internals, like every other capacity limit. The pool is sized explicitly (`DB_POOL_SIZE` 10 + `DB_MAX_OVERFLOW` 20 per process), and Postgres runs with `max_connections=200` in the production compose file.
- **Regression:** `tests/test_pool_exhaustion.py`: a pool timeout gives 503 with no leaked `QueuePool` text; the engine is sized from settings.

### QA-004 / QA-005 — Queued-search robustness (Low)
- **QA-004 (restart mid-queue):** queued selfies are memory-only by design, so a restart loses them, but the status said "queued" for up to 15 minutes. Each API process now writes a Redis heartbeat (`searchqueue:alive:<boot id>`, 30 s TTL, refreshed by the worker), and a queued job whose owner stopped beating reads "expired" at once; the page tells the user to search again. Regression: `tests/test_search_queue.py::test_restart_is_detected_quickly_not_after_the_ttl` (fails on old code).
- **QA-005 (duplicates):** the one-queued-search-per-user-and-event rule is now an atomic Redis `SET NX` claim, so it holds across API processes. It's released when the job finishes, and a stale claim from a lost job is taken over. Regression: `::test_duplicate_queueing_is_atomic_across_processes`, `::test_parallel_duplicate_submits_queue_once` (4 simultaneous submits → exactly one 202).
- **Result links (no finding):** the email links to the plain event page (no token), so it's reusable by its owner, shows another member only *their own* results, gives a non-member 403, and stops working when the recipient's access ends (`::test_result_link_shows_only_the_viewers_own_results`).

### Load at 10× expected concurrency
One API process (e2e server, `SEARCH_MAX_CONCURRENT=6`, queue 20) with 60 users searching at the same instant. After SEC-041/042:

| Outcome | Count | Timing |
|---|---|---|
| Served immediately | 13 | p50 4.9 s, p95 7.1 s |
| Queued | 21 | **all 21 completed**; time to "done" p50 13.5 s, p95 19.4 s |
| Busy (503 + Retry-After) | 26 | immediate |
| Other statuses / 5xx / tracebacks | **0 / 0 / 0** | |
| API memory | peak 1.4 GB | was 2.4 GB before SEC-041 |

(The harness itself was fixed too: `tests/e2e_server.py` now builds its fixture selfie frames once at start-up instead of 60 users building them concurrently.)

### UX pass (no spec existed; reviewed on real screens at 1280 px and 390 px)

| ID | Issue | Fix | Regression |
|---|---|---|---|
| UX-001 | Admin tab bar wider than a phone: the whole page scrolled sideways | Tab strip scrolls horizontally; tabs don't wrap | `e2e/ux.spec.ts` (no sideways scroll; every tab reachable, @xb) |
| UX-002 | Drive warning's long setting name overflowed its box on phones | Wraps (`break-all`) | Visual check |
| UX-003 | Scanning the QR code logged out: no context, and **sign-up lost the join link** (users ended at an empty "My events") | Log-in/sign-up say "to join the event"; the join destination travels through sign-up → verification email → verify page → log-in → join page with the code prefilled. The server accepts only `/join/<slug>[?code=…]` (no open redirect via email) | `tests/test_join_redirect.py` (15), `src/lib/join-next.test.ts`, `e2e/ux.spec.ts` full flow |
| UX-004 | No way to reach Account (consent withdrawal, delete my data) on phones | "Account" link on phones; Log out moved onto the Account page there | `e2e/ux.spec.ts` (@xb) |
| UX-005 | "(Phase 2)" build jargon in organizer settings | Shows the real service-account email to share the folder with | `e2e/ux.spec.ts` |
| UX-006 | "No date" printed everywhere for undated events | Date line hidden when absent | `e2e/ux.spec.ts` |
| UX-007 | Home copy said "take one selfie" / "deleted the moment the search finishes" (three shots; queued case) | Accurate copy | Visual check |
| UX-008 | MediaPipe info lines ("INFO: Created TensorFlow Lite XNNPACK delegate…") shown as red console errors (reported by the owner) | Known MediaPipe info/glog lines routed to `console.debug`; real errors unchanged | `src/lib/mediapipe-logs.test.ts` |
| UX-009 | Lowercase status badges ("approved") | Capitalized | Visual check |
| UX-010 | "My events" cards gave no hint they were clickable | "Find my photos →" call to action; badges grouped | `e2e/ux.spec.ts` |

Accessibility: axe now also covers the join-context log-in/sign-up pages, the queued-search card, the "Search queued" badge and the paused camera. **0 serious or critical violations.**

### Face-engine interface (owner's request)
`app/services/face_engine.py` defines `FaceEngine` (`detect`, `analyze_selfie`, `model_id`, `embedding_dim`). InsightFace moved to `face_engines/insightface.py` and is selected by `FACE_ENGINE` (`insightface` or `module:Class`); application code only calls `services/faces.py`, unchanged. Faces record their `model` (migration 0009), `search_faces` never compares across models (mutation-checked), and `python -m app.cli reindex-faces [--all]` moves photos to a new engine. Misconfiguration (unknown engine, wrong embedding size) fails fast at start-up. Privacy obligations for remote engines are in the interface docstring and the README. Regression: `tests/test_face_engine.py` (9, including a contract test against the real model and a swap to a fake engine by configuration alone).

### Re-run evidence
- **Backend:** 1,202 tests passed, 96% line coverage.
- **Scanners:** `scripts/security-scan.sh` 18/18.
- **Frontend:** 59 unit tests.
- **Playwright:** 31 in Chromium, WebKit, Pixel 7 and iPhone 14; Firefox (Linux image) 4/4.
- **ZAP** on the rebuilt production image: 0 FAIL, the same 6 justified warnings.

## Follow-up feature: queued searches with notification (2026-09-30)

Built at the owner's request after SEC-039, on branch `async-search`. When no face-work slot is free within 5 s, a fully validated search (rate limits, capture token, body) is queued in the API process's memory and answered with **202**. The page shows "You're in the queue" and polls `GET /api/events/{id}/search-status`, "My events" shows "Search queued" / "Photos ready", and a background worker runs the search when a slot frees up, then emails a **link only** (no photos, no counts).

Privacy and security review of the design:
- **Selfies stay in memory only.** A Celery/Redis queue was rejected because it would write biometric data to Redis (and possibly its disk). Redis holds only the per-user status (state, timestamps, match count, rejection reason), with a 24 h TTL. Tests scan Redis for image data (`tests/test_search_queue.py::test_queued_selfies_never_leave_memory`).
- **Consent:** the text now states that selfies may wait in memory for up to 15 minutes when the service is busy (the version was bumped to `2026-09-30`, so users re-consent once). The privacy page is updated.
- **Re-checked at run time:** a revoked member, withdrawn consent, a deleted account or an ended event → the job is dropped, with no grants and no results email (`::test_revoked_before_processing_cancels_the_job`, `::test_consent_withdrawn_before_processing_cancels_the_job`, `::test_account_deletion_forgets_search_state`).
- **Bounded:** at most 20 jobs and 64 MB of selfies per process; one queued search per user per event (409); a full queue → 503 before the body is read (`::test_full_queue_answers_busy`, `::test_queue_memory_is_bounded_in_bytes`, `::test_one_queued_search_per_user_and_event`). The worker takes a face slot from the same cap as synchronous searches and holds no DB connection during face work (SEC-038).
- **Restarts lose queued jobs by design:** the status then reads "expired" after 15 minutes and the user is asked to search again (`::test_lost_job_is_reported_as_expired`).
- **Authorization:** the status endpoint is event-member only and returns only the caller's own job (`::test_status_is_private_to_its_owner`; added to the authorization matrix, now 68 operations).
- **End to end:** `frontend/e2e/queued-search.spec.ts` (saturated server → queued card → badge → results on the open page → email with link → "Photos ready").

## Theme switcher and per-event accents (2026-10-01)

Built at the owner's request: System (default) / Light / Dark, a teal + midnight re-theme, and organizer accent colours per event (owner's decisions, 2026-10-01).

**Design, and why it needs no script:** the preference lives in the `ef_theme` cookie (first-party, `SameSite=Lax`, `Path=/`, 1 year; not `HttpOnly` because the switcher writes it, and it holds nothing sensitive). The root layout reads it on the server and renders `<html data-theme="light|dark">`, the matching `theme-color` meta and `color-scheme`. "System" (and a missing or tampered cookie) renders no attribute: `globals.css` then applies the dark tokens under `@media (prefers-color-scheme: dark)`, so the first paint is right in every mode and System follows OS changes live, with no inline script and **no CSP change**. Signed-in users: `users.theme` (Postgres enum, migration 0010) is the source of truth; login, refresh and `PATCH /api/me/preferences` set the cookie from it, so another device's first page after login is already correct. The gallery and photo viewer are `.theme-dark` islands (always dark), which the switcher and the settings page state.

**Security review (no new vulnerabilities):**
- **Theme value:** a three-value enum at every layer: pydantic `ThemePreference` (422 for anything else, including CR/LF and markup), the Postgres enum, and `parseThemePref` on the server render (anything unknown means System; React escapes attributes anyway). Regression: `backend/tests/test_theme.py` (30, including CSRF and login/refresh cookie sync), `src/lib/theme.test.ts`, `e2e/theme.spec.ts` "tampered theme cookie" and "API accepts only the three theme values". Mutation-checked: loosening the schema to `str` fails 15 tests; returning the cookie value unparsed fails the unit and e2e tests.
- **Accent colour:** it ends up in a `style` attribute (`style-src 'unsafe-inline'` is the existing accepted risk for style attributes), so only `#rrggbb` is accepted: pydantic validator (normalised to lowercase), a DB `CHECK` constraint, and a client-side regex before use. `url(…)`, `expression(…)`, `;`, `!important`, short hex and named colours are rejected (`test_accent_color_accepts_only_hex`, 10 cases; `test_database_rejects_malformed_accent`). Mutation-checked (6 tests fail without the validator; the DB constraint is the second layer).
- **Authorization:** `PATCH /api/me/preferences` acts only on the caller (matrix: 69 operations). Event accents are editable only through the existing organizer `PATCH /api/events/{id}`.
- **CSP:** unchanged. `e2e/theme.spec.ts` injects a nonce-less inline `<script>` into the real HTML response and asserts it doesn't run and raises a `script-src-elem` violation, while the app's own nonced scripts still run. ZAP baseline re-run on the rebuilt production web image (2026-10-01): **0 FAIL, 61 PASS, the same 6 justified warnings**; `scripts/security-scan.sh` 18/18.

**Readability:** all text/background token pairs are ≥ 4.5:1 in both themes (lowest 5.1:1 light, 6.0:1 dark), checked from the stylesheet itself by `src/lib/theme-tokens.test.ts`, which also asserts the three copies of the dark set are identical. Organizer accents are nudged in lightness (hue kept) until they reach 4.5:1 on every surface of each theme, and the on-accent text colour is picked per theme (`src/lib/accent.ts`; 12 sample colours including pure yellow, white and black in `theme.test.ts`; in-browser check of the real button in both themes in `e2e/theme.spec.ts`).

| ID | Finding | Fix | Regression |
|---|---|---|---|
| QA-006 (Low) | Found by axe once `/account` (the settings page) was added to the audited screens: the inline privacy link differed from the text around it by colour only, in both themes | Underlined | `e2e/a11y.spec.ts` "settings (account) page", light and dark |
| UX-011 | Visual review of the new mobile screenshots: the photo viewer's toolbar squeezed its labels to one word per line on phones | The toolbar wraps onto a second row | `e2e/visual.spec.ts` viewer baselines (Pixel 7) |

Caught before merge (not shipped): the 44 px theme button pushed the organizer header 13 px past a 390 px iPhone (`e2e/ux.spec.ts` "no sideways scroll"); fixed by tighter link padding on phones.

**Tests added:** backend 30; vitest 26 (theme, accent, token pairs); Playwright `theme.spec.ts` (12: System default in light and dark emulation, live OS change, persistence across reload and a new browser session, profile sync to a second browser context, first-frame "no flash" probe recorded before hydration, keyboard/ARIA/44 px/announcement, 180 ms transition that is off under reduced motion and absent on load, dark viewer in light mode in Chromium and Firefox, accent contrast, tampered cookie, API values, CSP); axe in **both themes** on every main screen (landing and auth, events, consent, capture, results, viewer, all organizer tabs, settings, queued and paused states); visual baselines for landing, settings, organizer list and event, capture, results and viewer in both themes on desktop Chromium and Pixel 7 (28 screenshots, volatile content masked, `e2e/visual.spec.ts-snapshots`).

## Mobile API for the iOS app (Phase 0, 2026-10-01)

Backend changes for the native iOS app (plan approved 2026-10-01). Goal: the app is **never a weaker path** than the web app. The event, photo, search, upload and privacy endpoints are shared unchanged: the same dependencies, rules and limits apply whichever transport authenticated the user.

**What was added:**
- **Bearer transport:** access JWTs carry an audience (`web` = httpOnly cookie only, `mobile` = `Authorization` header only). A request with an `Authorization` header is judged on it alone (cookies are ignored).
- **CSRF:** the check is skipped only for cookie-less requests that carry `Authorization` (a cross-site page can't add it; CORS is off), or for the cookie-free sign-in endpoints.
- **Passwordless sign-in** (`/api/mobile/auth/code/*`, `/magic`):
  - 6-digit codes are stored as HMACs in Redis, never in the DB. They live 10 minutes, are single-use and die after 5 wrong guesses.
  - Wrong guesses also count toward the same email+IP lockout as web join codes (5 → 15 min).
  - Requests are rate-limited per address and per IP and always get the same answer.
  - The magic link is single-use and kills the code. Passwords are never hashed on this path (no Argon2 load, SEC-041).
- **Device-bound sessions** (`devices` table, migration 0011):
  - An app session is the web session model (a refresh-token family in `auth_tokens`) plus a Secure Enclave P-256 key.
  - Refreshing needs an ECDSA signature by that key over (token hash, device, time), fresh (±60 s) and never reused, for a token of that device's own session. A copied refresh token is useless off the device.
  - The web refresh endpoint refuses app-session tokens.
- **Sign-out paths:** logout, device list/revoke, password reset and account deletion end app sessions exactly like web sessions.
- **Deleting a passwordless account** re-authenticates with an emailed `reauth` code. Sign-in codes can't be used for this.
- **Push (APNs, token auth, HTTP/2):**
  - Payloads are built only by `push.payload`: localization keys plus `kind`/`event_id`/`search_id`. No names, photos, counts or email addresses.
  - Sent after commit as a background task. Dead tokens are dropped, and a token moves with the install when someone else signs in on the same phone.
  - Off until configured; the production guard refuses a malformed key.
- **Forced updates:** app requests below `IOS_MIN_SUPPORTED_VERSION` (or without a version) get **426** before anything else runs. `/api/app/config` stays reachable.
- **Universal Links:** `/.well-known/apple-app-site-association` (JSON, no redirect, built from `APPLE_TEAM_ID`/`IOS_BUNDLE_ID`; admin and API paths excluded).
  - The browser fallback `/m/signin` drops the token from the URL with a 303 before rendering, and never spends it.
- **Event logos:** organizer upload as a raw body ≤ 1 MB, magic-byte sniffed, pixel-capped from the header, re-encoded to a metadata-free PNG ≤ 512 px. Members only, streamed; stored under the event prefix, so event deletion removes it.
- **API schema:** `backend/openapi.json` is the iOS client's source. A drift test fails until `python -m app.cli export-openapi` is re-run, and the raw selfie and logo bodies are documented in it.

**Regression and security tests (all new):**

| Area | Tests |
|---|---|
| Authorization matrix | Every operation × 9 roles × **2 transports** (cookie and bearer): **1,364 cells**, identical outcomes required. New operations: 14 (83 in total, incl. the theme endpoint). A new `CREDENTIAL` class asserts that a session never substitutes for body credentials (device-signed refresh → 401 for every role). |
| `tests/test_mobile_auth.py` (47) | Codes: account creation, no enumeration, no cookies set, single use, replacement, attempt limit, lockout, rate limit, expiry, concurrent first sign-in. Magic link single use. Bad device keys. Existing password accounts. Passwordless accounts can't use the password login. Refresh rotation; tampered key, stale/future time, wrong device, garbage signature. **Replayed signed request** (with zero reuse grace, so a replay would otherwise sign the user out). Reuse detection revokes the session. Cross-device and cross-transport refresh tokens. Token confusion (cookie ↔ bearer, hand-made wrong-audience JWT). Bearer ignores cookies. Malformed `Authorization` never authenticates and never switches CSRF off. Logout, device list/revoke, **IDOR on device revoke (404)**, password reset and web logout parity, re-auth for deletion, code purposes don't mix, push registration and token format. |
| `tests/test_push.py` (17) | Payload key whitelist per kind. APNs request format (ES256 provider JWT with `kid`/`iss`, topic, push type), with no email or event name in the body. Only live devices in the configured environment. Dead-token handling (410/400 dropped; 429/500 kept). Off until configured. Production key guard. Network errors. Errors never reach the caller. The real client is HTTP/2. Queued-search push. Moderation push goes to organizers only. |
| `tests/test_app_version.py` (16) | Missing, old and malformed versions → 426; supported versions pass; the gate runs before sign-in; config is reachable; browsers unaffected. |
| `tests/test_logo.py` (8) | Re-encode, bound and keep transparency; EXIF/GPS stripped; text, truncated PNG and > 1 MB refused; **100 MP pixel bomb refused before decoding**; delete removes the object; stored under the event prefix. |
| Other | `tests/test_openapi_contract.py` (drift check, documented raw bodies). `tests/test_endpoint_contracts.py` (new endpoints: malformed / missing / mistyped bodies → 422; 5 new rate-limited endpoints → 429). Migration round trip with a device and a passwordless user (the downgrade maps NULL → `'!'` and the upgrade maps it back, lossless). vitest `aasa.test.ts`. Playwright `mobile-links.spec.ts` (AASA served, sign-in link landing strips and keeps the token, logo upload → shown to attendees). |

**Mutation checks:** each guard was removed in turn, and the named tests failed every time:
- bearer-ignores-cookies, audience check, device signature, signature replay cache, token-belongs-to-device-session
- code attempt limit, code lockout, web refresh refusing app tokens, CSRF "no auth cookie" condition
- app-version gate, push payload whitelist, re-auth code purpose, device-revoke ownership, logo re-encode

The replay-cache mutant was initially **not** caught: within the 20 s reuse grace, a replay fails harmlessly anyway. The test now runs with zero grace, which is the case the cache exists for, and the mutant is caught.

**Caught before merge (not shipped):**
- **Refresh-path bypass:** the web cookie refresh endpoint would have rotated an app session's refresh token without the device signature. It now refuses device-session tokens (`test_app_refresh_token_is_refused_by_the_web_refresh_endpoint`).
- **Passwordless login crash:** a password login against a passwordless account would have reached Argon2 with `None` and raised (a 500). It now takes the dummy-hash path like an unknown email (`test_passwordless_accounts_cannot_log_in_with_a_password`).
- **Token in the page:** a sign-in link opened in a browser embedded the token in the page's RSC payload (same-origin only, never sent anywhere). The proxy now strips it with a 303 before rendering.
- **Scan harness noise:** the first ZAP API runs reported 5xx responses. Every one came from the e2e harness's own `/__e2e/event` seeding endpoint (test-only; it refuses to start outside `ENVIRONMENT=test`), fuzzed because it appears in the e2e server's schema. The scans were re-run against the production schema (`backend/openapi.json`); results are under "Scanner results".

**Coverage of the new modules:**

| Module | Coverage |
|---|---|
| `push.py` | 100% |
| `app_version.py` | 100% |
| `csrf.py` | 100% |
| `routes/mobile.py` | 98% |
| `deps.py` | 98% |
| `routes/events.py` | 98% |
| `mobile_auth.py` | 97% |

The whole app is at 96%. Backend: **2,098 tests** passing.

**Residual risks (iOS-specific, tracked for later phases):**
- **App Attest:** built in Phase 7, report-only (see "App Attest, report-only"). Until enforcement, a scripted client can call the same endpoints the web app can, under the same limits.
- **Anonymous app calls:** the app needs a session for everything except sign-in and config. Anonymous public flows (removal requests) stay on the web.
- **Universal Links and push** can only be verified end-to-end with an Apple Developer account and a real domain (Phase 4/7). Here they are covered by the AASA content tests and a fake APNs server.

## App Attest, report-only (iOS Phase 7, 2026-10-02)

Owner decision: build App Attest in Phase 7, **report-only first**. Nothing is blocked: results are recorded so enforcing can be decided on real data.

**What was added:**
- `services/app_attest.py`: Apple's attestation checks in Apple's order:
  - certificate chain to the **pinned Apple App Attestation Root CA** (signatures, names, validity, CA constraints)
  - nonce = SHA-256(authData ‖ SHA-256(challenge)) equals the credential certificate's extension
  - key id = SHA-256 of the certificate's public key
  - RP ID = SHA-256(Team ID.bundle id); counter 0; AAGUID matches the environment; credential id = key id
  - validation category and bundle version recorded when present
- Assertion checks: signature over SHA-256(authenticatorData ‖ SHA-256(clientData)), RP ID, and a counter that must increase. The client data is the device-signed refresh message, which is already time-bound and single-use.
- Endpoints `POST /api/me/devices/current/attest/challenge` (app sessions only, single-use per device, 5 min, rate-limited) and `POST /api/me/devices/current/attest`. The optional `assertion` field on `/api/mobile/auth/refresh`. Migration 0012 (device columns; the attested key id is unique).
- `python -m app.cli attest-report`: counts per status and reason code, with no user or device data.
- **No new dependency:** the attestation format is CBOR, so a minimal decoder (definite lengths only, depth and size caps) was written instead of adding a CBOR library.
- Production refuses `APP_ATTEST_ENV=development` once App Attest is configured.

**Tests (`tests/test_app_attest.py`, 52; plus the matrix, contracts and config):**
- A test CA shaped like Apple's builds real attestations.
- 16 rejection cases, each with its exact reason code. Among them: an impostor chain that copies the names, expired and non-CA intermediates, a development key in production and vice versa.
- The pinned root's fingerprint; a test-CA attestation refused against Apple's root.
- CBOR edge cases: indefinite length, tags, floats, truncation, depth, duplicate keys.
- Assertions: replayed counter, other key, other client data, wrong RP ID.
- Recording: single-use and device-bound challenges, key reuse across devices refused, failed attestations block nothing, assertions bound to their refresh.
- Both transports in the authorization matrix; the rate-limit contract.

**Found by the fuzz test (fixed before use):** the `cryptography` library parses certificates lazily. A corrupted certificate in an attestation therefore raised `ValueError`, `UnsupportedAlgorithm` or `InvalidVersion` from inside later checks, which the endpoint would have answered with a 500. The verifier now maps any parser error to `AttestError("malformed")`. 20,000 mutated attestations and 2,000 random CBOR inputs only ever produce `AttestError`.

**Also fixed:** `test_rate_limited_list_matches_the_code` only counted handlers on `@router.` and missed `@me_router.` handlers. It now counts every router.

**Mutation checks:** the test suite caught all 12 mutants:
- chain trust, CA constraint, certificate validity
- nonce, key id, counter 0, AAGUID, credential id
- assertion counter replay, key reuse
- challenge single use (GETDEL → GET), CBOR depth cap

**Full re-run after Phase 7:**
- backend **2,225 passed**, 0 failed (134 skips are the matrix's by-design transport cells);
- `scripts/security-scan.sh` **18/18** (after the 3 fixes under "Scanner results");
- ZAP API scans 0 FAIL, all three variants (see "Scanner results").

**Web re-run (Playwright):**
- The first run failed the capture/results visual test, plus load-dependent flakes that passed alone and in the re-run.
- The visual failure was a test-design flaw. The consent line shows today's date outside a `<time>` element, so it wasn't masked and the baseline went stale overnight. The seeded event name's random suffix also shifted its mask's width.
- Fixes:
  - the date is now a `<time dateTime>` element (better markup, masked like other dates);
  - the visual tests seed a fixed event name (`/__e2e/event?name=`), so names are compared, not masked;
  - baselines regenerated and inspected.
- Final: **64 passed** (Chromium, WebKit, mobile Chrome/Safari) and **5 passed** in Firefox (Linux image).

**Residual:**
- App Attest exists only on real devices, so it can't run in the simulator. The client path is tested with a fake provider; the server path is tested with the test CA. **Verify on TestFlight** (ios/APP_STORE.md) before deciding to enforce.
- Fraud-risk receipts (Apple's server-to-server metric) are not used; the receipt is not stored.

## Legal documents and provable acceptance (2026-10-03)

Owner request: real terms on web and app, plus a cookie section. The owner decided:
- the operator's identity stays as placeholders until founded;
- organizers pay and attendees are free;
- the organizer is the controller for event photos, with EventFaces as processor (Art. 28);
- minimum age 16.

**What was added:**
- `services/legal.py`: Terms of Use, Organizer Terms with the data processing agreement, Privacy Notice (including a dedicated cookie section) and Impressum. They are German (binding) and English, versioned, and served by `GET /api/legal/{document}` to web (`/terms`, `/organizer-terms`, `/privacy`, `/imprint`) and app (sign-in, Settings › About).
- **Operator identity** (`LEGAL_*`): production refuses to start while a required field is empty. Optional fields (register, VAT ID) disappear when empty.
- **Acceptance:**
  - every account creation (web sign-up, invitation, app sign-in) requires `accept_terms` ("Terms + at least 16") and writes a `legal_acceptances` row (document, version, time, language, web/ios);
  - a changed version must be accepted before further use: 403 + `X-Required-Action`, and web and app show the acceptance screen;
  - accepting a version the user wasn't shown is refused (409);
  - organizers accept the Organizer Terms and DPA before managing events;
  - account, deletion, consent withdrawal, devices and sign-out never depend on acceptance.
- **Cookies:** the four first-party, strictly necessary cookies are listed with purpose and lifetime (lifetimes from the live settings). No banner is needed (§ 25(2) no. 2 TDDDG). A test fails if the API sets a cookie the notice doesn't list.

**Tests and checks:**
- `tests/test_legal.py` (30):
  - pinned version hashes;
  - both languages structurally equal;
  - cookie honesty;
  - placeholders and optional fields;
  - public endpoint;
  - acceptance required and recorded on every creation path;
  - gates and their exemptions;
  - stale-version refusal;
  - super admin exemption;
  - deletion.
- Mass assignment: client-sent versions are ignored.
- Authorization matrix: both new operations, both transports.
- Six guards mutation-checked:
  - the Terms gate;
  - the Organizer Terms gate;
  - the stale-version check;
  - must-accept;
  - sign-up recording;
  - app recording.
- Web: Playwright `legal.spec.ts`:
  - footer documents in both languages;
  - the cookie section;
  - sign-up blocked until ticked;
  - Terms and Organizer Terms acceptance after a version change.
- Web: the axe audit now covers the legal pages.
- iOS:
  - `LegalTests` (unit and integration);
  - `LegalUITests` (sign-in blocked until ticked, all documents from Settings in both languages with audits, acceptance after a change).

**Found while building:**
- `accept_terms` accepted `"yes"` and `1` (Pydantic lax mode). It is now `StrictBool`, so only `true` counts.
- iOS: an acceptance request arriving while another sheet was open could never be shown. The app now closes the sheet first.
- iOS: a container identifier hid the document view's Close button (IOS-018 again). The identifier moved to the scroll view.

**Final gates (2026-10-04):**

| Gate | Result |
|---|---|
| Backend | **2,296 passed**, 0 failed |
| `scripts/security-scan.sh` | **18/18** |
| iOS gate | iPhone 17 **112/112**, iPad Air **112/112**, screen matrix on iPhone 17e and 18 Pro Max **4/4** each |
| Playwright | **75 passed**, plus Firefox **7/7** |

- One scan run hit 3 transient failures in steps that download data: pip-audit (advisory database), semgrep (rule registry) and the image build. Each passed when run alone, and a full rerun passed 18/18.
- Playwright: the e2e login helper had a pre-existing race. The page's own start-up request could replace the CSRF cookie between the token request and the login, which the server correctly refused (403). The helper now sends the cookie value actually in the jar and retries once on that refusal.

**Not legal advice:** the texts are engineering drafts tailored to the service. LEGAL_REVIEW.md lists what counsel must decide. The biggest open point is the legal basis for face templates of everyone in event photos (Art. 9).

## UAT foundations, phase 1: CI, error reporting, releases (2026-10-04)

Owner request before UAT (treated as production): automated checks on every change, error
reporting with alerts, and a release/deploy/rollback procedure. Owner decision: self-hosted
GlitchTip (no third-party error service).

**What was added:**
- **Error reporting (GlitchTip, Sentry protocol, same server):**
  - Backend: `sentry-sdk[fastapi,celery]` (approved dependency), off unless `SENTRY_DSN` is set. The SDK never collects bodies, PII or local variables, and `core/monitoring.scrub` filters every event (request reduced to method, path and safe headers; user reduced to the opaque id; messages, exceptions and breadcrumbs redacted for tokens, emails and bearer tokens).
  - Web: **no SDK** (SDKs record clicks, console and URLs on pages that hold selfies). Browsers post a few string fields to the same-origin `/monitoring` route, which redacts them and builds the event itself for a server-only DSN. It never forwards client-built envelopes (no open relay or SSRF), accepts only same-origin posts and caps size and rate. Server errors go through `instrumentation.ts`. The CSP is unchanged (`connect-src 'self'`).
  - iOS: no SDK; Apple's crash reports are used.
  - Production guard: `SENTRY_DSN` required (https, or plain http only to the internal `glitchtip` host); GlitchTip's secret key and DB password are checked for strength.
  - GlitchTip runs hardened: read-only root, all capabilities dropped, no-new-privileges, digest-pinned, memory limit, its own DB role and database with no access to the app database, no Valkey (the app's Redis is untouched), sign-up off, 30-day retention.
- **Alerts:** new or regressed issues by email; uptime monitors; heartbeats from the retention job (only after a successful run), the backup and `scripts/disk-check.sh` (checks in only while healthy).
- **Releases:** `/api/health` reports the build version. `scripts/release.sh` (clean `main`, CI green on the commit, annotated tag, notes from merged PRs) and `scripts/deploy.sh`. The deploy does a pre-deploy dump (mode 600, newest 3 kept, older ones shredded), builds, starts, runs `scripts/release_check.sh`, and **rolls back automatically**: alembic downgrade first, restore from the dump if that fails. `scripts/rollback.sh` refuses to guess after a rollback.
- **CI** (`.github/workflows/ci.yml`): backend, web, e2e (all browser projects), security scan; iOS on demand (`ios/scripts/test.sh --no-api`). Actions are pinned by commit SHA, `permissions: contents: read`, no secrets, no credential persistence. actionlint is clean.

**Tests and checks:**
- `tests/test_monitoring.py`:
  - a real crash during a selfie search reports no email, token, selfie header or cookie value, with request keys limited to method, path and headers;
  - SDK options;
  - the scrubber;
  - the retention heartbeat only after success;
  - a heartbeat sends no data and never raises.
- `tests/test_infra_config.py`: nine new production-guard cases.
- `src/lib/error-report.test.ts` (14): redaction, stack parsing, DSN parsing, field allow-list, envelope, tunnel refusals, rate limit.
- `e2e/monitoring.spec.ts` against a fake GlitchTip in `e2e_server.py`: in every browser project an uncaught error arrives redacted; rejections are de-duplicated; cross-site posts are refused.
- **Mutation-checked:** 10 backend and 11 web guards. Each removal fails a test. Two survivors in the first round (breadcrumb data, SDK body size) got new tests.
- **Against a real GlitchTip 6.2.6**, in the same hardened configuration:
  - events from API, worker and web are stored with nothing personal;
  - a heartbeat check-in is recorded;
  - Caddy routes `errors.<domain>` over TLS.
- **Production-stack rehearsal** (`docker-compose.prod.yml`, production mode, random secrets, throwaway clone; local test data only):

  | Scenario | Result |
  |---|---|
  | First deploy | Release check 27/27 |
  | Failed deploy (bad health and a new migration) | Automatic downgrade and rollback; earlier data intact |
  | Good deploy, then `rollback.sh` | Back to the previous version and schema |
  | Failed deploy whose downgrade also fails | Restored from the pre-deploy dump; database grants re-applied (app may connect, GlitchTip may not) |

**Found while building:**
- The backend scrubber left an **email address** in exception messages: caught against the real GlitchTip, now redacted, and covered by a test.
- Error reports include source context lines, so leak tests build their secrets at run time.
- The browser reporter registered after hydration, so early errors were lost. It now installs on module load.
- `Sec-Fetch-Site` is missing on plain-http origins (Firefox in the Linux e2e container). The tunnel now falls back to comparing `Origin` with `Host`.
- Stack-parsing regex flagged by eslint-plugin-security: rewritten without overlapping quantifiers, input bounded (an adversarial line takes about 0 ms).
- `deploy.sh`: the compose file fixes `.env.prod` by name; the web proxy needed a moment after the API container was replaced (health is retried for up to 60 s); bash 3.2 compatibility; a curl fallback that printed `000000`.

**Final gates (2026-10-04):**

| Gate | Result |
|---|---|
| Backend | **2,311 passed**, 0 failed (136 skipped: authorization-matrix cells that don't apply to a transport) |
| `scripts/security-scan.sh` | **18/18** |
| Frontend | lint clean (no new warnings), `tsc`, vitest **103/103**, production build |
| Playwright | **81 passed** (Chromium, WebKit, Pixel 7, iPhone 14), plus Firefox (Linux image) **8/8** |
| iOS | API schema unchanged (no regeneration needed); `ios/scripts/test.sh --no-api` **86/86** on iPhone 17 and iPad Air |
| Workflow | actionlint clean; shellcheck clean on every new script |

- The first full backend run had one failure: the new retention-heartbeat test called `.delay().get()`, which Celery refuses once an earlier test has left a task context behind (test order). The test now calls the task body directly, as the worker does. Both mutants (no check-in, check-in before the run) still fail it.
- The first scan run found two things in new test code, both fixed in code rather than suppressed:
  - gitleaks: a random-looking literal password in a test fixture, now derived from the shared test constant;
  - semgrep: a Firefox-style stack line (`fn@http://host/...`) matched the "credentials in URL" rule, so the fixture is now built from a host variable.
- CI itself runs once the branch is pushed (not yet: needs the owner's go-ahead).


## UAT phase 2: pricing and test-mode payments (2026-10-05)

Owner decisions: per-event plans plus a monthly subscription; a successful checkout creates the event (self-service); a dummy payment integration until a real provider is chosen.

**What was added:**
- **Price list** (`services/billing/plans.py`, the only source):

  | Plan | Price | Attendees | Photos |
  |---|---|---|---|
  | Event S | €49 | 100 | 500 |
  | Event M | €149 | 500 | 3,000 |
  | Event L | €349 | 2,000 | 10,000 |
  | Pro | €199 a month | 5 events a month, Event M limits each | |

  Prices include 19% VAT and are marked as example prices.
- **Provider interface** with a `FakeProvider` that behaves like Stripe Checkout:
  - a hosted payment page (in this app, TEST MODE banner);
  - test cards only (4242… succeeds; 4000…0002 and 4000…9995 fail);
  - a server-to-server confirmation signed with HMAC-SHA256 over `timestamp.body`, valid for ±300 s.
- **Orders:**
  - only a verified confirmation pays an order;
  - each provider event applies once (`webhook_events`), and only a pending order is fulfilled;
  - a confirmation whose amount or currency differs from the order never fulfils.
- **Fulfilment:** the event is created with the plan's limits, the buyer becomes its organizer (attendee → organizer), and the existing Organizer Terms + DPA gate still applies before managing.
- **Subscriptions:**
  - 30-day periods; the allowance is counted from orders, so deleting an event doesn't give the slot back;
  - canceling keeps the subscription until the period ends;
  - hourly maintenance renews or ends subscriptions and cancels checkouts unpaid after 24 h.
- **Plan limits**, with the event row locked against races:
  - attendees on join (slug and code) and on invite acceptance;
  - photos on guest uploads and Drive import (Drive skips the excess and reports it on the sync run);
  - admin-made events stay unlimited.
- **Web:** pricing page, checkout, test payment page (card fields with autofill off), Account › Billing (orders, receipts, subscription, new event from the allowance), plan usage on the event's admin page.
- **iOS:** no purchase UI (App Store rules); the API schema only grows.
- **Account deletion:** orders are kept (invoice retention) but unlinked, and a running subscription ends immediately.
- **Production guard:** the fake provider is refused unless `ALLOW_TEST_PAYMENTS=true` (UAT); `PAYMENTS_WEBHOOK_SECRET` must be strong.

**Found while building:**
- **FastAPI echoed rejected input in every 422 response**, e.g. a too-short password at sign-up (and it would have echoed card numbers). A global handler now returns only `type`, `loc` and `msg`, with a regression test.
- Postgres `now()` is the transaction start, so an event created in the same transaction as the subscription looked older than the period. Usage is now counted from orders, using the app clock on both sides.
- The webhook table's `event_id` column (the provider's event id) tripped the GDPR test that checks every `event_id` column after an event is deleted. It is renamed to `provider_event_id`.
- The checkout summary had a text line directly inside a `<dl>` (axe: serious). It now sits outside the list.
- `webhook_events` has no foreign key, so the per-test cleanup didn't empty it, and an id from one test leaked into the next. It is now truncated explicitly.

**Tests:**
- `tests/test_billing.py` (27): purchase, Organizer Terms gate, declined card, non-test cards refused and never echoed, own-orders-only, signed webhook applied once, forged/stale/future/unsigned/tampered confirmations refused, wrong amount, CSRF scope, oversized body, subscription allowance and cancellation, maintenance, attendee/invite/upload/Drive limits, unlimited admin events, account deletion.
- Authorization matrix: 10 new operations, both transports. Rate-limit contract: 4 new endpoints.
- **16 guards mutation-checked:** signature, timestamp, test cards only, amount, fulfil once, allowance, one subscription, cancellation ends, deletion ends the subscription, own orders, attendee limit, upload limit, Drive limit, CSRF cookie scope, 422 no-echo, production guard.
- Playwright `billing.spec.ts`: buy Event S (real card refused, declined card, then success) → event admin with plan usage → billing → receipt. The axe audit covers pricing, checkout, test payment, billing and receipt in both themes.

**For counsel (LEGAL_REVIEW.md item 6):**
- the right of withdrawal for an immediately starting service (checkbox wording needed);
- invoice retention and billing details;
- the example prices.

**Final gates (2026-10-05):**

| Gate | Result |
|---|---|
| Backend | **2,525 passed**, 0 failed (no new warnings) |
| `scripts/security-scan.sh` | **18/18** |
| Frontend | lint clean (no new warnings), `tsc`, vitest **106/106**, production build |
| Playwright | **81 passed** (Chromium, WebKit, Pixel 7, iPhone 14), plus Firefox (Linux image) **8/8** |
| iOS | regenerated API client builds; `test.sh --no-api` **86/86** on iPhone 17 and iPad Air |

- **Visual baselines:** the "settings" baselines were regenerated after the intended change (the new Billing card on the account page) and inspected in both themes, desktop and phone.
- **One transient failure in the full Playwright run:** the dark-theme "delta pass" axe test, a screen this phase didn't touch. It passed 9 of 9 reruns.
- **The first scan run found two things in new code**, both fixed in code:
  - the three new forms lacked `method="post"` (`forms.test.ts`): before hydration, a submit would have put the fields, including a card number, into the URL;
  - a secret-looking literal in a test fixture (gitleaks), now built at run time.


## UAT phase 3: one-page landing page and contact form (2026-10-05)

**What was added:**
- **Landing page** (`/`), one scrolling page:
  - hero with a "contact sheet" of abstract photo tiles (theme colours, no people, no images), where one load-time animation dims the crowd and outlines "your" frames; with reduced motion only the end state shows;
  - how it works, for attendees and for organizers (numbered, because they are sequences);
  - a dark privacy panel with six concrete promises;
  - features;
  - pricing (the same component as `/pricing`);
  - FAQ (`details`/`summary`);
  - contact form, and a final call to action.

  A sticky in-page nav uses an IntersectionObserver to mark the section in view (`aria-current`). Smooth scrolling is off with reduced motion. The CSP is unchanged: no inline scripts and no external assets.
- **Contact form** (`POST /api/contact`):
  - emailed to `CONTACT_EMAIL` (else `LEGAL_EMAIL`) with Reply-To set to the sender, and never stored;
  - rate limited per IP and per sender (the Redis key is a SHA-256 of the address);
  - a filled honeypot field gets a "sent" answer and nothing is sent;
  - a mail outage answers 503 + Retry-After and logs only the error type.

**Found while building:**
- **Log assertions in the test suite were vacuous for 10 app loggers.** Alembic's `fileConfig` (migrations run in-process in conftest and the e2e server) disabled every logger that already existed, including `photo_pipeline`, `search_queue` and `main`. So "no selfie or embedding in the logs" (`test_search_abuse.py`) never saw those modules' output. `alembic/env.py` now keeps existing loggers; `tests/test_logging_setup.py` asserts that no app logger is disabled (mutation-checked). The selfie-logging test still passes, now for real.
- The logged-out header with the new "Pricing" link overflowed at 320 px. The link is hidden below 370 px; the landing page's section nav covers it.
- In dark mode the privacy panel merged with the page background. It now has a border.

**Tests:**
- `tests/test_contact.py` (12): delivery and Reply-To, nothing persisted (row counts of every table), recipient fallback, header injection (model and form), honeypot, validation, per-sender rate limit, outage without details.
- Authorization matrix and rate-limit contract cover the endpoint.
- Guards mutation-checked: honeypot, per-sender limit, Reply-To flattening, Reply-To set, error-type-only logging (a first mutant survived because of the disabled logger above).
- `e2e/landing.spec.ts`: section nav and scroll-spy (all browser projects), FAQ, contact message delivered (captured outbox), pricing → checkout login.
- The axe audit covers the landing page in both themes; no sideways scroll at 320, 360, 375 or 414 px.

**For counsel (LEGAL_REVIEW.md item 15):** mention the contact form in the Privacy Notice, and confirm the landing page's public promises.

**Also found in the full run:** the theme menu opened *behind* the new hero tiles. The header's `backdrop-blur` makes it a stacking context, so the menu's `z-40` only applied inside it. The header now has `relative z-30`. The existing theme-switcher e2e tests caught it, and now guard it.

**Final gates (2026-10-05):**

| Gate | Result |
|---|---|
| Backend | **2,559 passed**, 0 failed, with all app loggers live |
| `scripts/security-scan.sh` | **18/18** |
| Frontend | lint clean (no new warnings), `tsc`, vitest, production build |
| Playwright | everything except macOS Firefox passes, plus Firefox (Linux image) **9/9** |
| iOS | `test.sh --no-api` **86/86** on iPhone 17 and iPad Air (API schema: the contact endpoint added) |

Playwright details:
- After the header fix, the theme and landing specs passed **18/18** in Chromium and WebKit, and the landing spec in WebKit, Pixel 7 and iPhone 14.
- The **landing visual baselines** were regenerated (intended: a new page) and inspected in both themes, desktop and phone.

**CI (GitHub Actions) bring-up**, from the first real runs on PR #5. Each problem was fixed and documented:
- `tsc` needs `next typegen` first (the scan now runs it);
- the dev web container can't use a bind mount of the runner's checkout (`docker-compose.ci.yml` runs it from its image);
- the containers can't write caches into the checkout (`chmod -R a+rwX .` in CI);
- SeaweedFS sized its volumes from free disk space and ran out on the e2e runner (`PutObject InternalError`). The volume count is now fixed (`-volume.max=50`, 256 MB volumes).
- A backend hang seen once no longer appears; `faulthandler_timeout=300` will name it if it returns.
- **The runner ran out of disk** (trivy: "16 MB free"; also the likely cause of the SeaweedFS errors). Docker-heavy jobs first delete the runner's unused preinstalled SDKs (~25 GB).
- **Charts drew wider than the screen for one frame** (fallback width before measuring): phones briefly scrolled sideways, which the ux spec caught on CI's mobile projects. The SVG is now capped at its container (`max-w-full`); both mobile projects passed 18/18 twice in the Linux image.
- **The e2e reset could deadlock** with a search still finishing from the previous test (TRUNCATE vs. its audit insert). It now retries on deadlock (test server only). Capture steps get 60 s to appear on CI's slower CPUs (a wait, not a weaker check).
- **A real bug found by CI in Linux WebKit:** the photo viewer's single download never started after the ZIP download. Downloads were link clicks that navigated and then turned into downloads; the link now carries `download` (same-origin), so it downloads directly. Reproduced and verified in the Linux Playwright image (Chromium, Firefox, WebKit, iPhone 14) and on macOS.


## Look and feel: event identity, results reveal, QR poster (web, 2026-10-05)

Owner request: make the app more distinctive. Items 1–3 of the proposal, on the web; the iOS app follows in a later phase.

**What was added:**
- **Event identity** (`components/event-cover.tsx`): every event page, the join page and the event lists now open with a cover band in the event's accent colour. The band is topped by a "contact sheet" pattern seeded by the event's id, with the logo on a paper chip.
  - The title sits on solid accent below the faded pattern, so the tested accent contrast still holds.
  - The join preview API adds `accent_color` and nothing else; a test pins its exact fields, since it's visible before joining.
- **Results reveal:**
  - "You're in N photos" headline; fresh results lift in once with an accent frame (none with reduced motion);
  - a justified photo layout that keeps aspect ratios, using the stored width and height;
  - the viewer gains swipe, a filmstrip (`aria-current`), focus moved into the dialog and visible previous/next buttons.
- **Printable QR material** (`/admin/events/[id]/poster`, organizers only, reached from the Access tab):
  - an A4 poster or four A6 table cards in the event's colours, printing exactly one A4 page (checked with Chromium's PDF output);
  - always light, through a new `.theme-light` island that a test keeps equal to the light tokens;
  - the site header and footer are hidden in print.
- **Link preview** (`app/opengraph-image.tsx`): a branded 1200×630 image for every page, rendered with `next/og` (part of Next; no new dependency). It never names an event: join links require a login, so crawlers land on `/login`. `SITE_URL` (production compose) makes the image URL absolute.

**Found while building:**
- With a fixed column count the cover tiles became slabs on desktop. They now have a fixed size, and wider screens get more of them.
- The pattern's rows spilled under the title on wide screens; the strip now clips.
- The reveal's final keyframe, with fill-mode `both`, would have permanently replaced the tiles' `ring` (box-shadow); it uses `backwards`.
- Per-event patterns made the visual baselines differ on every run. They are marked `data-volatile` (the suite's mask convention), and two runs in a row now match.

**Tests:**
- `event-cover.test.ts`: the pattern is deterministic per event, distinct between events and faint.
- `e2e/identity.spec.ts`:
  - covers on the event, list and join pages (all browsers);
  - the headline count;
  - viewer focus, filmstrip and swipe;
  - poster and table cards, and the print view;
  - the link-preview image.
- The axe audit covers the lists, join page, event page and poster in both themes.
- Backend: the exact join-preview fields.

**Final gates (2026-10-05):**

| Gate | Result |
|---|---|
| Backend | **2,560 passed** |
| vitest | **110/110** |
| Build | production build passes |
| Playwright | all projects pass (after test locators were updated for the filmstrip), plus Firefox (Linux image) **10/10** |
| Visual baselines | regenerated, inspected, stable over two runs |
| iOS | `--no-api` **86/86** (schema: `accent_color` on the join preview) |
| Security scan | **18/18** |

## Scanner results

| Tool | Scope | Initial | Final | Notes |
|---|---|---|---|---|
| pip-audit | backend + ML requirements | 33 vulns / 4 pkgs | **0** | SEC-001 |
| bandit | `backend/app` all severities | 3 (2×B101, 1×B105) | **0** | B105 = token-type name → `# nosec` with justification |
| ruff (E,F,W,B,S,UP,SIM,PL,RUF,ASYNC,PERF) | `backend/app` | 10 | **0** | 2 `PLW0603` test-injection hooks justified inline |
| mypy | whole app; strict on 12 authn/authz modules | 42 (+6 strict) | **0** | |
| semgrep (python, owasp-top-ten, secrets, js, ts, react, dockerfile, docker-compose) | repo | 2 | **0** | README placeholder reworded (was a false positive); SEC-006 |
| gitleaks | full git history + working tree | 0 history / 18 tree | **0** | 18 were generated, git-ignored caches → path allowlist in `.gitleaks.toml` |
| Re-scan, iOS Phase 7 (2026-10-02) | all 18 steps | 3 FAIL | **18/18 PASS** | **mypy:** 2 real typing gaps in the new App Attest code; one was a missing `None` check (a device removed between the session check and the row lock), now answered with 401. **gitleaks (tree):** Xcode derived data in the git-ignored `ios/build/` (third-party OpenAPIKit test fixtures) → path allowlist like `node_modules/`; and the declaration `let key: P256.Signing.PrivateKey` in `DeviceKey.swift` matched `generic-api-key` (its "secret" is the Swift type name) → exact-value allowlist (`^P256\.Signing\.PrivateKey$`), not key material. **trivy config:** one HIGH in an example Dockerfile inside a SwiftPM checkout under `ios/build/` → that directory skipped; the project's own Dockerfiles have 0 findings. The git-history scan still covers everything committed. |
| npm audit | frontend | 0 | **0** | |
| eslint + eslint-plugin-security | frontend | 17 warnings | **0** | `detect-object-injection` off with justification (SEC-007) |
| tsc --noEmit | frontend | 0 | **0** | |
| trivy config | Dockerfiles | 0 | **0** | compose checked by `scripts/check_compose.py` (trivy doesn't parse compose) |
| trivy image | prod API / web images | 133 / 8 HIGH | **44 / 0** (re-run 2026-09-30: 0 fixable) | 44 = base-Debian, no upstream fix → R-1 |
| pip-audit re-run (2026-09-30) | dev + prod API image | 7 (pip 25.0.1 ×6, pytest 8.3.5) | **0** | SEC-040 |
| ZAP baseline | web app, **production image** (re-run 2026-09-30) | 0 FAIL, 10 WARN | **0 FAIL, 6 WARN** | Each WARN justified below (§ZAP warnings) |
| ZAP API scan (OpenAPI), unauthenticated | API | 0 FAIL, 2 WARN | 0 FAIL, 1 WARN | CORP fixed; `ef_csrf` not HttpOnly = double-submit design (test-enforced) |
| ZAP API scans, **Phase 0 re-run** (2026-10-01, production schema `backend/openapi.json`) | API: unauthenticated, cookie-authenticated, **bearer-authenticated (iOS app path)** | — | **0 FAIL** in all three (117/116/116 PASS); **0 tracebacks** in the API log | Warnings: `ef_csrf`/`ef_theme` not HttpOnly (double-submit and theme-switcher design), "Server" header from the local scan proxy (R-4). The first run's 5xx all came from the e2e harness's `/__e2e/event` (see "Mobile API") |
| ZAP API scans, **iOS Phase 7 re-run** (2026-10-02, production schema incl. App Attest endpoints) | API: unauthenticated, cookie-authenticated, bearer-authenticated | — | **0 FAIL** in all three (117/115/115 PASS); **0 tracebacks** in the API log; both authenticated sessions still alive at the end | Status mix through the proxies, ~9,600 requests each: mostly 422 (fuzzing) and 403 (other events), with 200s present. **A first attempt was invalid and was discarded**: a fuzzed logout ended the scan session mid-run, and the first fix (re-login on any 401) then hit the sign-in code limit (5 per 15 min), because the device-signed refresh endpoints answer 401 to every fuzzed token by design. That left 29,222 requests failing inside the proxy. `scripts/zap_auth_proxy.py` now excludes the two logout endpoints (they are covered by the unauthenticated scan and the tests), signs in again only when `/api/me` shows the session really ended, logs a status mix, and reports its own failures as `proxy-error` (0 in the valid runs). New warning, a proxy artifact: "CORP header missing" on the proxy's synthetic 204 replies for the excluded logouts; the API itself sends `Cross-Origin-Resource-Policy: same-origin`. |
| ZAP baseline, Phase 0 re-run | web app, production image incl. `/m/signin`, `/terms`, AASA | — | **0 FAIL, 6 WARN** (same justified set) | AASA served as JSON (200, no redirect); sign-in links 303 to the token-free page |
| ZAP API scan, **authenticated** | API | — | 0 FAIL | ~6,500 attack requests, **0 × 5xx, 0 tracebacks**. The first two "authenticated" runs were silently unauthenticated (ZAP's replacer does not add missing headers; 0 × 200). Fixed with `scripts/zap_auth_proxy.py`, verified by response mix (200s present, no 401s). |

### ZAP warnings: justification (production image, 2026-09-30)

| ID | Alert | Instances | Why it stays |
|---|---|---|---|
| 10202 | Absence of Anti-CSRF Tokens | 5 forms | No form ever submits natively with side effects (SEC-018 added `method="post"` only as a fallback that goes nowhere). Every state change is a `fetch` to `/api/*` carrying the double-submit `X-CSRF-Token` header, enforced by `CSRFMiddleware` (`tests/test_auth.py::test_csrf_required_for_mutations`). ZAP only recognises form-field tokens. |
| 10055 | CSP: `style-src 'unsafe-inline'` | 5 | Residual risk R-2 (React `style={}` attributes can't carry nonces). Scripts are nonce + `strict-dynamic` only. |
| 90004 | Cross-Origin-Embedder-Policy missing | 5 | COEP only enables cross-origin isolation (`SharedArrayBuffer`, high-resolution timers), which the app doesn't use. COOP and CORP `same-origin` are set (SEC-020). |
| 10111 | Authentication Request Identified | 2 | Informational: ZAP found the login form. |
| 10019 | Content-Type Header Missing | 1 | `/account` while logged out is an empty-body redirect to `/login` from `proxy.ts`. |
| 10049 | Storable/Non-Storable Content | 7 | Informational: content-hashed `/_next/static` chunks are immutable (by design); pages are `no-store`. |

The dev server adds three more that don't exist in production: `'unsafe-eval'` and `ws:` for hot reload (dev-only CSP), and `eval(` inside React's dev bundle.


## Load test (k6)

`loadtest/eventfaces.js` against the e2e API (`docker-compose.load.yml`): 1 uvicorn process, Celery inline (so upload "complete" includes ingest + indexing that production runs in the worker), Docker Desktop on an Apple-silicon Mac, test data only. Configurable rate limits were raised and every simulated user had its own client address, so the run measures capacity. The hard-coded per-user capture-token limit was left as is and still returned 429 under load (check passed). 225 s: searches ramping 1→40 virtual users, 3 VUs downloading ZIPs, 2 VUs uploading. 3,067 requests, **0 errors** (after the SEC-038 fix).

| Operation | n | p50 | p95 | p99 |
|---|---|---|---|---|
| Selfie search (3 shots) | 198 | 12.9 s | 26.8 s | 27.2 s |
| ZIP download (ticket + stream) | 618 | 0.49 s | 0.96 s | 1.11 s |
| Guest upload (start + PUT + complete incl. inline indexing) | 166 | 1.8 s | 7.9 s | 12.2 s |

| Concurrent searches | p50 | p95 | p99 |
|---|---|---|---|
| 6–10 | 5.3 s | 6.7 s | 6.7 s |
| 11–20 | 9.9 s | 15.2 s | 15.6 s |
| 21–30 | 20.3 s | 26.6 s | 26.7 s |
| 31–45 | 23.7 s | 27.2 s | 27.3 s |

**After SEC-039 (search cap 6 per process), same scenario:** 421 search attempts: 145 answered (p50 7.9 s, **p95 12.0 s, p99 12.5 s**, flat from 11 to 45 concurrent users) and 276 turned away with a busy 503 at p95 5.1 s. Downloads p95 1.2 s, uploads p95 2.9 s, 0 errors, 0 tracebacks. Throughput is unchanged (it's bound by the serialized face model); what changed is that waiting is bounded and memory with it.

**Breaking point:** no request errors up to 44 concurrent users. Search throughput plateaus at ≈0.9/s per API process (face model serialized per process), so with p95 ≤ 10 s as the target, the breaking point is ≈12 concurrent searches per process. Before SEC-038 was fixed, the breaking point was an outright failure: DB pool exhaustion at ≈15 concurrent searches took down unrelated endpoints. Capacity scales with API processes (production runs 2 per container; add replicas for peaks). See SEC-039.

## Accepted residual risks

| # | Risk | Why accepted / mitigation |
|---|---|---|
| R-1 | 44 HIGH CVEs in Debian base packages of the API image (util-linux, login, ncurses, perl-base) with **no upstream fix** | Not reachable from the app (no setuid use, no shell exposure, non-root read-only container). `apt-get upgrade` runs at build time; `security-scan.sh` fails as soon as any becomes fixable (`--ignore-unfixed`). Rebuild images regularly. |
| R-2 | CSP `style-src 'unsafe-inline'` | React `style={}` attributes can't carry nonces. Scripts are strictly nonce + `strict-dynamic`, so injected markup can't execute script; style injection alone can't read cookies (httpOnly) or call the API (CSRF header). |
| R-3 | `ef_csrf` cookie is readable by JavaScript | By design (double-submit CSRF: the page must copy it into `X-CSRF-Token`). It is not an auth credential; auth cookies are httpOnly (`test_only_the_csrf_cookie_is_script_readable`). |
| R-4 | ZAP API scan's "Server header" warning | Came only from the local authenticating test proxy (`scripts/zap_auth_proxy.py`). Production uvicorn runs with `--no-server-header` behind Caddy. |
| R-5 | Refresh-token replay within 20 s of a legitimate rotation is refused but doesn't revoke the session (SEC-022) | Needed so two tabs refreshing at once don't log the user out. Outside the window a replay revokes the whole session. Tunable via `REFRESH_REUSE_GRACE_SECONDS` (0–120). |
| R-6 | No self-service data export (GDPR Art. 15/20) | Adding it would be a feature, out of scope for this pass. The data per user is small and fully enumerable (memberships, grants, uploads, feedback, audit rows). Operators answer access requests manually; recommended as a follow-up. |
| R-7 | No per-account login throttle across many IPs | A per-account lockout would let anyone lock a victim out. Mitigations: argon2 hashing, per IP+email and per-IP limits (`test_login_rate_limited`, `test_lockout_also_applies_per_ip_across_accounts`), generic errors. Put a WAF/bot filter in front for credential-stuffing waves (checklist). |
| R-8 | Face-matching accuracy measured on a synthetic set only | No consented real selfie/event pairs were available (and real face data must not be used for testing without consent). The pipeline, thresholds and tiers are covered; calibrate `FACE_MATCH_THRESHOLD`/`MATCH_BEST_THRESHOLD` on consented pilot data (the match-quality dashboard suggests thresholds from feedback). |
| R-9 | Firefox e2e runs only in the Linux container locally | Playwright's macOS Firefox build doesn't start on macOS 27. The Linux run covers the Firefox engine; re-check the native macOS build when Playwright updates it. |
| R-10 | Search capacity is fixed per process (SEC-039 cap) | Busy users get a clear "try again" within about 5 s instead of a long wait. Size `SEARCH_MAX_CONCURRENT` and the number of API processes for the expected peak. An asynchronous "we'll notify you" flow was discussed as a possible follow-up (not implemented). |
| R-11 | Benign deprecation warnings in the test run (botocore `utcnow`, Starlette/httpx, InsightFace `estimate`) | Library-internal; no behavioural impact. Re-check on the next dependency upgrade. |
| R-12 | Load figures come from one dev machine (Docker Desktop, 1 API process, inline Celery) | Treat them as relative, not absolute. Re-run `loadtest/eventfaces.js` on production-like hardware before launch. |


## How to re-run everything

Everything runs against the local stack with test data. From the repo root:

```bash
cp .env.example .env                                   # first time only
docker compose up -d --build                           # dev stack

# Backend: all unit/integration/security tests (incl. authz matrix, contracts, boundaries,
# concurrency, migrations, accuracy, static analysis: ruff, mypy, bandit)
docker compose exec api pytest -q
docker compose exec api pytest -q --cov=app --cov-report=term          # coverage
docker compose exec api pytest -q tests/test_authz_matrix.py           # authorization matrix only

# Frontend unit tests, lint, types, build
cd frontend && npm ci && npm run lint && npx tsc --noEmit && npx vitest run && npm run build && cd ..

# All scanners (pip-audit, ruff, mypy, bandit, npm audit, eslint, tsc, vitest, semgrep,
# gitleaks history + tree, compose policy, trivy config + images, prod-image checks)
scripts/security-scan.sh            # add --zap for a ZAP baseline scan of the web app

# End-to-end (Playwright): swap the API for the e2e server, then run the browsers
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api web
cd frontend && npx playwright install chromium firefox webkit   # first time only
npx playwright test                                             # Chromium full suite + @xb in WebKit/mobile (+ Firefox where it runs)
# Firefox via Playwright's Linux image (macOS 27 can't start the macOS Firefox build):
docker run --rm --network eventfaces_default --ipc=host -v "$PWD:/work" -w /work \
  -e E2E_BASE_URL=http://web:3000 -e E2E_API_URL=http://api:8000 \
  mcr.microsoft.com/playwright:v1.63.0-noble npx playwright test --project=firefox
cd .. && docker compose up -d api                               # back to the dev API

# Load test (k6), results in loadtest/results/
docker compose -f docker-compose.yml -f docker-compose.e2e.yml -f docker-compose.load.yml up -d api
docker compose -f docker-compose.yml -f docker-compose.e2e.yml -f docker-compose.load.yml --profile load \
  run --rm k6 run --out json=/scripts/results/raw.json /scripts/eventfaces.js
docker compose up -d api

# Backup/restore drill
scripts/backup_restore_drill.sh

# Clean-checkout run (what the final gate used): copy only what git would check out,
# then build and test under a throwaway compose project with empty volumes.
D=$(mktemp -d) && git ls-files -co --exclude-standard -z | xargs -0 -I{} rsync -R "{}" "$D/"
cd "$D" && cp .env.example .env && docker compose stop -t 5 2>/dev/null; docker compose -p eventfaces-ci up -d --build
docker compose -p eventfaces-ci exec api pytest -q
docker compose -p eventfaces-ci down -v
```


## Production hardening checklist

What code alone can't cover. The API already refuses to start in production with development secrets or insecure settings (SEC-033); this list covers the rest.

**TLS & edge**
- [ ] DNS for `DOMAIN`, ports 80/443 only; Caddy obtains certificates automatically. Confirm HSTS and the security headers on the live domain (`curl -I`).
- [ ] Put a CDN/WAF in front (e.g. Cloudflare) with bot and credential-stuffing rules for `/api/auth/*`, `/api/join`, `/api/removal-requests*` (R-7), and request-rate caps per IP.
- [ ] Keep `TRUSTED_PROXY_HOPS` equal to the real number of proxies that *overwrite* `X-Forwarded-For` (1 for Caddy alone; add 1 only for a CDN that replaces the header).

**Secrets & keys**
- [ ] Generate `JWT_SECRET`, `DOWNLOAD_TOKEN_SECRET`, `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` and `REDIS_PASSWORD` with `openssl rand -base64 48`; store them in a secret manager, never in git (gitleaks guards the repo).
- [ ] Rotate on staff changes or suspected leak, at least yearly. Rotating `JWT_SECRET` logs everyone out; rotating `DOWNLOAD_TOKEN_SECRET` voids links (they live 2 minutes).
- [ ] Scope the storage (R2/S3) key to the one bucket, with object read/write only; scope the Google service account to Drive read-only on the shared folders.

**Data protection (GDPR, biometric data)**
- [ ] Complete a DPIA (Art. 35): face embeddings are special-category data (Art. 9).
- [ ] Sign DPAs with processors (hosting, storage, SMTP) and keep EU data residency (e.g. R2 EU jurisdiction).
- [ ] Publish the privacy notice (`/privacy`) and the removal-request link at every event.
- [ ] Decide who answers Art. 15/20 access requests (R-6) and within what time (1 month).

**Backups**
- [ ] Nightly `pg_dump -Fc`, **encrypted** (backups contain embeddings), stored off-host with retention no longer than the longest data retention (audit log 365 days). Keep bucket versioning or replication with the same limits.
- [ ] Run `scripts/backup_restore_drill.sh`-style restore tests quarterly, against the production backup format.

**Monitoring & alerting**
- [ ] Alert on `/api/health` failures, 5xx rate, p95 latency (searches: ≈0.9/s per API process, see Load test), Celery queue length (`celery`, `index`), and a missing hourly retention log line.
- [ ] Alert on bursts of 401/403/429 (brute force, scraping) and on `Refusing to start in production` in logs.
- [ ] Size API processes and `SEARCH_MAX_CONCURRENT` for the expected peak search rate (≈0.9 searches/s per process; cap = throughput × acceptable wait). Watch the rate of 503 "busy" responses as the capacity signal.

**Logs**
- [ ] Keep Caddy access logs off, or apply the same token redaction as `app/core/logging.RedactTokens` (SEC-030).
- [ ] Retain application logs for 30–90 days; they contain IDs and IP addresses (personal data), never selfies or embeddings (tested).

**Patching**
- [ ] Run `scripts/security-scan.sh` weekly in CI and on every dependency change. Rebuild images at least monthly to pick up base-image fixes (R-1).
- [ ] Re-check the pose conventions and MediaPipe telemetry guard when upgrading InsightFace or `@mediapipe/tasks-vision` (CLAUDE.md).

**Incident response**
- [ ] Name a security contact and a data-protection contact; publish `/.well-known/security.txt`.
- [ ] Breach runbook: contain (rotate secrets, revoke sessions by rotating `JWT_SECRET`), assess, notify the supervisory authority within **72 hours** (Art. 33) and affected people if the risk is high (Art. 34); biometric data raises the risk level.
- [ ] Keep the per-event removal-request flow staffed: requests land in the organizer's Moderation tab.

