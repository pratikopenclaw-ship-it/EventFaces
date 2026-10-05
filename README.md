# EventFaces

Event attendees find their photos by uploading a selfie. Organizers link a Google Drive folder; photos are indexed with face embeddings; attendees join an event, consent, take a selfie, and download the photos they appear in.

**Status:** Phases 1–6 complete: auth, roles, events, join by code/QR or CSV invites with magic links, Google Drive import with face indexing, consent-gated selfie search, signed downloads, guest uploads with moderation, reports, retention jobs, delete-my-data, removal requests from people in photos, audit log, and production deployment setup.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind v4) |
| API | FastAPI, SQLAlchemy 2 (sync, psycopg 3), Alembic |
| DB | Postgres 16 + pgvector |
| Jobs | Celery + Redis (beat for scheduled jobs) |
| Storage | S3 API — SeaweedFS locally, R2/S3 in production |
| Faces | InsightFace `buffalo_l` (RetinaFace + ArcFace, 512-d), onnxruntime CPU; model baked into the image |
| Email | SMTP — Mailpit locally |

> MinIO no longer publishes container images, so local dev uses SeaweedFS's S3 gateway. The app only speaks the S3 API (boto3), so production R2/S3 is unaffected.

## Local setup

Requirements: Docker with Compose v2. Nothing else runs on the host.

```bash
cp .env.example .env          # dev defaults work as-is
docker compose up -d --build  # db, redis, s3, mailpit, api, worker, beat, web
docker compose exec api python -m app.cli create-superadmin --email you@example.com
```

| URL | What |
| --- | --- |
| http://localhost:3000 | Web app |
| http://localhost:8000/api/docs | API docs (disabled in production) |
| http://localhost:8025 | Mailpit — verification & reset emails land here |

The API container runs `alembic upgrade head` and creates the storage bucket on start.

## Google Drive import

1. In Google Cloud: create a project, enable the **Google Drive API**, create a **service account**, and add a JSON key. (No billing needed for read-only Drive API use within default quotas.)
2. Put the key in `.env`, either inline as `GOOGLE_SERVICE_ACCOUNT_JSON='<the key file contents on one line>'` or mount the file and set `GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/drive.json`.
3. Organizer: share the Drive folder with the service account's `client_email` (Viewer), paste the folder URL in the event's Settings, then press **Sync now** on the Photos tab.

What a sync does: lists top-level JPEG/PNG/HEIC files (paginated, retries 429/5xx/rate-limit 403s with backoff) → inserts only unseen `drive_file_id`s → per photo: download, re-encode (strips EXIF/GPS), store original (≤6000px), preview (1600px) and thumb (400px) → detect every face and store one embedding per face. Re-syncing only imports new files and retries transient failures; unreadable files are marked rejected and skipped. Subfolders are not imported.

## Selfie search

1. The attendee sees a consent screen (GDPR Art. 9(2)(a)) before their first search. Consent is versioned (`FACE_CONSENT_VERSION` in `app/services/search.py`); bump it when the text changes and everyone is asked again. Withdrawing deletes the user's matches.
2. The selfie is taken with the browser camera (file upload only if the event enables it) and POSTed as the **raw request body**, not multipart, because Starlette spools multipart uploads over 1 MB to temp files on disk. It is decoded, embedded and matched in memory, then discarded.
3. The search compares the largest face in the selfie against faces **of that event only** (published photos), using the HNSW index with pgvector iterative scans.
4. Matches become `search_grants` (user ↔ photo, expires after `SEARCH_GRANT_DAYS` or at event access end), and one `search_audit` row records user, event, time and match count.
5. Downloads: the client requests a signed token (JWT with `DOWNLOAD_TOKEN_SECRET`, 2-minute expiry, bound to user + event + photos), then fetches `/api/downloads/<token>`. On redemption, the user, membership and per-photo rights are checked again. Photos stream from storage, and several photos stream as a ZIP.

**Busy servers: "we'll notify you".** Face analysis takes seconds of CPU and runs one search at a time per API process, so each process admits at most `SEARCH_MAX_CONCURRENT` (default 6) searches. A search that can't get a slot within `SEARCH_QUEUE_WAIT_SECONDS` (5 s) is still validated and then **queued in that process's memory** (`app/services/search_queue.py`, at most `SEARCH_OVERFLOW_QUEUE_SIZE` jobs and `SEARCH_QUEUE_MAX_BYTES`). The API answers 202, the page shows "You're in the queue" and polls, "My events" shows a badge, and the user gets an email ("Your photos from … are ready", with a link only) when the background worker finishes. The worker re-checks membership, consent and the account before matching. Selfies never leave memory (no Redis, disk or storage), so a restart loses queued searches; their status turns "expired" after `SEARCH_QUEUE_TTL_SECONDS` (15 min) and the user is asked to search again. With the queue full or disabled (`SEARCH_OVERFLOW_QUEUE_SIZE=0`), busy searches get 503 "try again in a few seconds".

**Face engine.** The model sits behind `app/services/face_engine.FaceEngine`; application code only calls `services/faces.py`. `FACE_ENGINE=insightface` (default) or `FACE_ENGINE=package.module:Class` for any other implementation (GPU build, another open model, or a cloud API). Each face row records the model that produced it and search only compares embeddings from the current model, so after switching run `python -m app.cli reindex-faces` (add `--all` to re-scan photos where the old model found nobody) and recalibrate the thresholds. Engines must return L2-normalised 512-d embeddings (else add a migration) and follow the pose convention in the interface docstring; `tests/test_face_engine.py` checks the contract. An engine that sends images to a third party moves biometric processing outside your infrastructure: that needs a DPA, an EU region, updated consent text (`FACE_CONSENT_VERSION`) and a DPIA update.

**Tuning the threshold.** `FACE_MATCH_THRESHOLD` (cosine similarity, default 0.45) trades missed photos against strangers' photos. The test fixtures score ≥0.93 for the right person and ≤0.2 for others, but they're derived from the same photo. Real selfies against candid event photos usually score around 0.35–0.7 for the same person. Before going live, calibrate on a few real selfie/event pairs. Lower it (for example 0.38) if people report missing photos; raise it if strangers' photos show up.

## Guided selfie capture, quality gate & match feedback

- **Capture flow**: a requirements screen, then the browser camera with an oval overlay and live hints from **MediaPipe Face Landmarker**, auto-capturing three shots (front, slight left, slight right) when every check passes and the head is still. A manual shutter appears after 12 s; the server still validates every shot.
- **Capture token**: `POST /api/events/{id}/capture-token` issues a one-time token (60 s, bound to user + event, consumed atomically). Camera searches without a valid token get 403. File-upload selfies are possible only if `ALLOW_SELFIE_FILE_UPLOAD=true` **and** the event allows it (both are off by default).
- **Server quality gate** (`services/selfie_quality.py`, thresholds in `.env`): resolution ≥ 640×480, exactly one face, detection ≥ 0.8, face height 30–60% of the frame, yaw ±20° / pitch ±15° / roll ±15°, front shot within ±12°, side shots turned ≥ 5° the requested way, sharpness and brightness within range, and all three shots of the same person. Rejections return `{detail, code, shot}`, and the UI asks for a retake of that shot. Checks run root cause first (light, then sharpness, then confidence), so the message tells people what to actually fix.
- **Search**: each shot is searched separately inside the event, and each photo keeps its best similarity. Results are split into **Best matches** (≥ `MATCH_BEST_THRESHOLD`) and **Possible matches** (≥ `FACE_MATCH_THRESHOLD`). Selfies and embeddings are discarded after matching. The only things stored are per-shot quality *metrics* (`selfie_quality`: no image, embedding or user).
- **Feedback**: "This is me" / "Not me" on each result, and "Photos of me are missing". `match_feedback` takes face, similarity and search from the server-side grant, so the client can't forge them. "Not me" hides the photo now and in later searches. When the event's face data expires, consent is withdrawn or the account is deleted, the links to the user, face, photo and search are removed; verdict, similarity and event remain.
- **Match quality dashboard** (event tab "Match quality"; super admins: `/admin/match-quality`): feedback by similarity band with the current thresholds marked, wrong-match rate, missing reports, selfie quality distribution and rejection reasons. It also shows a **suggested threshold**: the lowest band edge where ≥ 90% of rated matches at or above it were confirmed, shown once there are ≥ 30 ratings.
- **MediaPipe is self-hosted** (`scripts/fetch-mediapipe.mjs` copies the WASM and downloads the model at build time, SHA-256 pinned), so visitors never contact Google. Note that tasks-vision **sends usage telemetry to Google (`odml.pa.googleapis.com`) with no opt-out**. The CSP blocks it, and a fetch guard in `guided-capture.tsx` stops it before it reaches the network (verified in the browser: zero third-party requests).

## Themes and event accents

Light, dark or System (default, follows the OS live): the sun/moon/monitor button in the header, or Account → Appearance. Guests keep the choice in a cookie; signed-in users also save it to their profile, so other devices follow after login. Pages render in the saved theme from the first byte (server-side `data-theme`, no inline script, CSP unchanged). Photos (results gallery and viewer) always show on a dark background. Organizers can set an accent colour per event (event settings); it is adjusted automatically to stay readable in both themes.

## Guest uploads, moderation and invites

- **Uploads** go straight from the browser to storage using a presigned PUT, which is limited to that one key, the declared size and the content type, and expires after 10 minutes. The storage server rejects anything else. On "complete", the API checks size and magic bytes. A worker then re-encodes the photo (stripping EXIF/GPS), deletes the raw object, and indexes it with the same `index_photo` step as Drive photos.
- **Moderation**: in `manual` mode, uploads wait in `pending_review` (indexed but never searchable) until an organizer approves them. Rejecting, deleting, or resolving a report with "remove photo" all go through `retire_photo`, which deletes the photo's embeddings, everyone's grants, and the files. A tombstone row is kept.
- **Abandoned uploads** (file never arrived) are hidden and deleted by an hourly beat job once the upload URL has expired.
- **CORS**: the bucket must allow `PUT` from `FRONTEND_URL`. `init-storage` sets this when the credentials permit it; on R2/S3, otherwise add the rule in the provider console.
- **Invites**: paste or upload a CSV. Each email gets a personal magic link, stored hashed, valid 14 days (`INVITE_DAYS`, capped at access end). It works only for the invited address: logged-in users with that email join in one click, and new users set a password directly (the link proves the email). Resending rotates the link. Revoked members can't use an old link to rejoin.
- **QR codes** (SVG on screen, PNG download) encode the join link including the access code. Rotating the code invalidates printed QR codes.

## Tests

```bash
docker compose exec api pytest -q                                   # all backend tests
docker compose exec api pytest tests/test_membership.py -k lockout  # one test
cd frontend && npm run lint && npx next typegen && npx tsc --noEmit # frontend checks
```

CI (`.github/workflows/ci.yml`) runs the backend tests, web checks, Playwright (all projects except `@visual`, whose baselines are macOS renders) and the security scan on every pull request; iOS unit tests on demand.

Backend tests run against a separate `eventfaces_test` database (created on first Postgres start) and Redis DB 15.

End-to-end tests (Playwright) run against `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api web`: `cd frontend && npx playwright test`. Firefox runs from Playwright's Linux image (its macOS build doesn't start on macOS 27): `docker run --rm --network eventfaces_default --ipc=host -v "$PWD:/work" -w /work -e E2E_BASE_URL=http://web:3000 -e E2E_API_URL=http://api:8000 mcr.microsoft.com/playwright:v1.63.0-noble npx playwright test --project=firefox` (from `frontend/`).

## Pricing and payments

Organizers buy per-event plans (Event S/M/L) or a monthly Pro subscription (5 events a month) at `/pricing`. Prices are example prices incl. 19% VAT, defined once in `backend/app/services/billing/plans.py`. Checkout runs through a provider interface; the only provider so far is a **fake one (TEST MODE)**: its payment page in this app accepts only test cards (4242 4242 4242 4242 succeeds, 4000 0000 0000 0002 is declined) and confirms with a signed webhook, exactly like a real provider would. A paid order creates the event with the plan's attendee and photo limits and makes the buyer its organizer. Orders, receipts and the subscription are under Account › Billing. Attendees never pay, and the iOS app has no purchase screens.

## Roles & access model

- **super_admin** — creates/deletes events, assigns organizers, sees everything. Created only via the CLI.
- **organizer** — manages the events where they have an `event_members` row with `role=organizer`.
- **attendee** — accesses events where they have an approved, non-expired membership.

Every event-scoped endpoint goes through `get_member_event` / `get_managed_event` (`backend/app/api/deps.py`), which return **403** unless the membership is approved and not expired. The event's `access_expires_at` ends attendee access; organizers keep access to manage retention.

## Security notes

- Auth: 15-min access JWT + rotating 14-day refresh token (hashed in DB), both `httpOnly` cookies; double-submit CSRF token on all mutations.
- The browser talks only to Next.js; `/api/*` is rewritten to FastAPI, so cookies are first-party.
- Rate limits: login, signup, password reset, join. Wrong access codes lock out per user+event and per IP+event (5 tries → 15 min).
- `TRUSTED_PROXY_HOPS`: leave `0` unless a trusted proxy appends to `X-Forwarded-For`; otherwise clients could spoof IPs to dodge rate limits.
- Secrets come only from env vars (`.env` is git-ignored).

## Privacy & retention

| Data | Kept until | Where enforced |
| --- | --- | --- |
| Selfie + query embedding | never stored (processed in memory) | `api/selfie.py`, `services/search.py` |
| Face embeddings of an event | event `access_expires_at` | `services/retention.py` (hourly) |
| Event photos | organizer's choice; optionally at access end | `delete_photos_on_expiry` |
| Search grants (user ↔ matched photo) | `SEARCH_GRANT_DAYS` or access end | retention job |
| Search audit (user, event, time, count) | `AUDIT_RETENTION_DAYS` (365); anonymized on account deletion | retention job |
| Removal requests | unverified 48 h; closed `REMOVAL_REQUEST_RETENTION_DAYS` (180) | retention job |
| Never-verified accounts | `UNVERIFIED_USER_DAYS` (14) | retention job |

- **Delete my data** (`/account`) hard-deletes the account, memberships, grants, uploads (files + faces) and invites. Audit rows and reports are anonymized.
- **Removal requests** (`/removal-request?event=<slug>`, link on the Access tab) let anyone who appears in photos, attendee or not, ask for removal, with an optional reference selfie that's matched in memory against that event only. The requester never sees the matches; organizers review them in the Moderation tab. A malicious requester could submit someone else's face, so organizers should check before removing.
- Extending an event's access after retention ran re-indexes its photos automatically.
- Legal texts: Terms of Use, Organizer Terms with the data processing agreement, Privacy Notice (with a cookie section) and Impressum, in German (binding) and English, served to web (`/terms`, `/organizer-terms`, `/privacy`, `/imprint`) and app from `backend/app/services/legal.py`. Acceptance is required at sign-up and recorded per version. Set the operator details (`LEGAL_*`) and have counsel review them: **LEGAL_REVIEW.md**. Face search is special-category (biometric) processing, so plan a **DPIA** (Art. 35 GDPR) and data processing agreements with your hosting, storage and email providers.

## Rate limits

| Endpoint | Limit (per window) |
| --- | --- |
| Login | 10 / 5 min per IP+email, 50 / 5 min per IP (`LOGIN_RATE_LIMIT`) |
| Signup / forgot password / resend verification | 10 / 5 / 5 per hour per IP |
| Join by code | 20 / 5 min per IP; 5 wrong codes → 15 min lockout per user+event and per IP+event |
| Selfie search | 10 / 10 min per user, 30 per IP (`SEARCH_RATE_LIMIT`) |
| Guest upload start | 60 / hour per user (`GUEST_UPLOAD_RATE_LIMIT`) |
| Download links | 60 / 10 min per user |
| Reports | 20 / hour per user |
| Removal requests | 5 / hour per IP, 3 / day per email; submissions 10 / hour per IP |
| Invites | 20 uploads / hour per event; resend 5 / hour per invite |
| Delete account | 5 attempts / hour per user |

## Deploying to production

**Step-by-step EU deployment (Hetzner + Cloudflare R2), email authentication, backups, monitoring, secrets and the go/no-go checklist: see [DEPLOYMENT.md](DEPLOYMENT.md).** The summary below is kept for orientation.

`docker-compose.prod.yml` runs Caddy (TLS), Next.js (standalone build), FastAPI (2 workers), a Celery worker, **one** Celery beat, Postgres + pgvector, Redis and GlitchTip (error reports, uptime and heartbeat alerts on `errors.<DOMAIN>`). Object storage (R2/S3) and SMTP are external.

1. **Server**: 4 vCPU / 8 GB RAM is comfortable. Each API/worker process loads the face model (~0.5 GB). Indexing runs at roughly 1 photo/s per worker process on CPU; add worker replicas for big imports.
2. **DNS**: point `DOMAIN` at the server (ports 80/443 open); Caddy fetches certificates.
3. **Storage (Cloudflare R2 example)**: create a private bucket (EU jurisdiction if you want data in the EU) and an API token with object read/write. Set `S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com`, `S3_PUBLIC_ENDPOINT_URL` to the same URL, `S3_REGION=auto`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`. Add a CORS rule allowing `PUT` from `https://<DOMAIN>` with header `content-type` (`init-storage` tries to set it automatically).
4. **`.env.prod`**: start from `.env.example` and set:
   - `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `FRONTEND_URL=https://<DOMAIN>`, `DOMAIN=<DOMAIN>`
   - `JWT_SECRET` and `DOWNLOAD_TOKEN_SECRET`: two different values from `openssl rand -hex 32`
   - `TRUSTED_PROXY_HOPS=1` (Caddy replaces client-supplied `X-Forwarded-For`; don't set this if anything else sits in front without the same guarantee)
   - strong `POSTGRES_PASSWORD` (schema owner, used only via `MIGRATION_DATABASE_URL` for Alembic) and a different strong `APP_DB_PASSWORD`; `DATABASE_URL` must use the least-privilege `eventfaces_app` role with that password
   - strong `REDIS_PASSWORD`, repeated in `REDIS_URL=redis://:<password>@redis:6379/0`
   - `SMTP_*` and `EMAIL_FROM` for your mail provider (with SPF/DKIM set up)
   - `GOOGLE_SERVICE_ACCOUNT_JSON` for Drive import
   - remove `TEST_*` variables
   The API refuses to start with `ENVIRONMENT=production` if any of these still has a development/public value (dev secrets, low-entropy secrets, identical JWT/download secrets, `COOKIE_SECURE=false`, non-https `FRONTEND_URL`, owner role or dev password in `DATABASE_URL`, Redis without a private password, dev S3 key, Mailpit as SMTP host); the error lists every problem.
5. Release with `scripts/release.sh vX.Y.Z` (laptop) and deploy with `scripts/deploy.sh vX.Y.Z` (server: backup, build, start, `scripts/release_check.sh`, automatic rollback; first deploy: DEPLOYMENT.md section 6), then `docker compose -f docker-compose.prod.yml exec api python -m app.cli create-superadmin --email you@yourdomain`.
6. **Backups**: nightly `pg_dump` (embeddings are only 2 KB/face) plus bucket versioning or replication. Backups contain biometric data: encrypt them and expire them in line with the retention table.
7. **Calibrate `FACE_MATCH_THRESHOLD`** with a few real selfie/event photo pairs before launch (see "Tuning the threshold").
8. **Monitoring**: GlitchTip error reports (scrubbed of personal data), uptime monitors on `/api/health`, and heartbeats from the retention job, the backup and `scripts/disk-check.sh` (DEPLOYMENT.md section 8). `/api/health` also reports the deployed version.

