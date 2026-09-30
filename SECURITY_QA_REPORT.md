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
| All tests green from a clean checkout | **Met** | Fresh copy of the tree (tracked + unignored files only, `.env` from `.env.example`), new compose project with empty volumes: build, `alembic` to head (0008), **1,140 backend tests passed, 0 skipped** (1,146 after the SEC-039 tests); frontend lint, tsc, 37 vitest tests and `next build` passed; **18 Playwright tests passed** against that stack (19 with the QA-002 test, re-run against the dev stack) |
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

**Totals:** 43 findings: 2 High, 14 Medium, 24 Low, 3 Info, and 0 Critical. **All 43 fixed**, each with a regression test.

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

## Scanner results

| Tool | Scope | Initial | Final | Notes |
|---|---|---|---|---|
| pip-audit | backend + ML requirements | 33 vulns / 4 pkgs | **0** | SEC-001 |
| bandit | `backend/app` all severities | 3 (2×B101, 1×B105) | **0** | B105 = token-type name → `# nosec` with justification |
| ruff (E,F,W,B,S,UP,SIM,PL,RUF,ASYNC,PERF) | `backend/app` | 10 | **0** | 2 `PLW0603` test-injection hooks justified inline |
| mypy | whole app; strict on 12 authn/authz modules | 42 (+6 strict) | **0** | |
| semgrep (python, owasp-top-ten, secrets, js, ts, react, dockerfile, docker-compose) | repo | 2 | **0** | README placeholder reworded (was a false positive); SEC-006 |
| gitleaks | full git history + working tree | 0 history / 18 tree | **0** | 18 were generated, git-ignored caches → path allowlist in `.gitleaks.toml` |
| npm audit | frontend | 0 | **0** | |
| eslint + eslint-plugin-security | frontend | 17 warnings | **0** | `detect-object-injection` off with justification (SEC-007) |
| tsc --noEmit | frontend | 0 | **0** | |
| trivy config | Dockerfiles | 0 | **0** | compose checked by `scripts/check_compose.py` (trivy doesn't parse compose) |
| trivy image | prod API / web images | 133 / 8 HIGH | **44 / 0** (re-run 2026-09-30: 0 fixable) | 44 = base-Debian, no upstream fix → R-1 |
| pip-audit re-run (2026-09-30) | dev + prod API image | 7 (pip 25.0.1 ×6, pytest 8.3.5) | **0** | SEC-040 |
| ZAP baseline | web app, **production image** (re-run 2026-09-30) | 0 FAIL, 10 WARN | **0 FAIL, 6 WARN** | Each WARN justified below (§ZAP warnings) |
| ZAP API scan (OpenAPI), unauthenticated | API | 0 FAIL, 2 WARN | 0 FAIL, 1 WARN | CORP fixed; `ef_csrf` not HttpOnly = double-submit design (test-enforced) |
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

