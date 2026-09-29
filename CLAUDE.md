# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

EventFaces: attendees find event photos via selfie face search. Built in phases (see README "Status"); after each phase run tests, summarize, and stop for the user's go-ahead. Ask before adding paid services or major dependencies. GDPR applies (face embeddings are biometric data).

## Commands

Everything runs in Docker; host Python (3.9) is not used.

```bash
docker compose up -d --build                         # full stack (dev)
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build   # production (see README)
docker compose exec api pytest -q                    # backend tests (test DB eventfaces_test, Redis DB 15, bucket eventfaces-test)
docker compose exec api pytest tests/test_auth.py::test_login_rate_limited
docker compose exec api alembic revision -m "msg"    # new migration (hand-write ops; files are NNNN_slug.py)
docker compose exec api python -m app.cli create-superadmin --email x@example.com
cd frontend && npm run lint && npx next typegen && npx tsc --noEmit && npm run build
```

Mailpit (dev email) UI: http://localhost:8025 — also has a JSON API at `/api/v1/messages` for grabbing verify/reset links.

## Architecture

- Browser → Next.js (:3000). `next.config.ts` rewrites `/api/*` → FastAPI, so auth cookies are first-party. Frontend is mostly client components calling `src/lib/api.ts` (adds `X-CSRF-Token`, retries once after `/api/auth/refresh` on 401).
- FastAPI (`backend/app`): `api/routes/*` (thin) → `services/*` (logic) → `models/*` (SQLAlchemy 2, **sync** sessions shared with Celery). `core/` holds config (pydantic-settings, env only), security, rate limiting, email, storage.
- Celery worker + beat (`app/workers/celery_app.py`, tasks in `app/workers/tasks.py`). Tasks are thin wrappers over `services/photo_pipeline.py`: `drive.sync` → `drive.import_photo` → `photos.index` (routed to the `index` queue). `index_photo` is the shared indexing step (guest uploads reuse it in Phase 4).
- Faces: `services/faces.py` (`detect_faces`) lazily loads InsightFace buffalo_l once per process from `/models` (baked into the image). The same image serves the API and the worker because the API embeds selfies in-process, so they never touch Redis or storage. The ML deps + model are in their own Docker layer (`requirements-ml.txt`); edit `requirements.txt` for everything else.
- `photos.status` is visibility (only `published` may ever be searchable); `photos.index_status` is pipeline progress. `faces.event_id` is denormalized for event-filtered vector search.
- Images: `services/imaging.py` sniffs magic bytes and re-encodes everything to metadata-free JPEG. Storage keys are `events/<event>/photos/<photo>/<variant>.jpg`; images reach browsers only via API streaming endpoints that check the photo belongs to the path's event.
- Storage is S3-API only (boto3). Local dev uses SeaweedFS (MinIO images are no longer published) — don't reintroduce MinIO.

## Security invariants (tests enforce these; keep them true)

- **Every event-scoped route** must depend on `MemberEvent` or `ManagedEvent` from `app/api/deps.py`. Authorization logic lives only in `app/services/membership.py`. Non-members get 403 (also for unknown event IDs, to prevent probing).
- `services/search.search_faces` takes `event_id` keyword-only and filters both `faces.event_id` and `photos.event_id`, plus `photos.status == published`. `test_selfie_never_returns_photos_from_another_event` must keep passing.
- Photo visibility for non-organizers is decided only by `services/photo_access.viewable_photos` (published + unexpired grant or own upload + same event). Thumbnails, previews and downloads all go through it.
- Never return raw storage or Drive URLs. Images stream through the API, and downloads use `services/downloads` tokens bound to user + event + photos and re-checked on redemption.
- Selfies and query embeddings are never persisted: the search endpoint reads the raw body (never `UploadFile`/multipart, which spools to disk), and `test_selfie_is_never_persisted` blocks tempfile use during a search.
- Guest uploads: the only storage URL a browser ever gets is the presigned PUT (`storage.presigned_put`, signs size + type). Never make `pending_review` photos visible: `viewable_photos` and `search_faces` both require `published`.
- Anything that takes a photo out of circulation must use `photo_pipeline.retire_photo` (deletes faces, grants, files) under a row lock. `index_photo` re-checks the row after detection so it never writes embeddings for a retired photo.
- Invites: `invites.accept` requires the logged-in email to equal the invited email and must never re-approve a revoked member.
- Retention (`services/retention.py`, hourly beat) deletes an event's faces/grants at `access_expires_at`; `index_photo` refuses to index events whose retention has run. Keep both in sync if you add new biometric or derived tables: add them to `retention.expire_event`, `account.delete_account` and consent withdrawal.
- Removal requesters must never be shown matched photos or counts (stranger could fish for someone else's photos).
- Camera searches require a capture token (`services/capture_tokens.py`, GETDEL single-use, bound to user+event) and a 3-shot `application/x-selfie-set` body (front,left,right). Selfie upload needs `ALLOW_SELFIE_FILE_UPLOAD` AND `event.allow_selfie_file_upload`.
- `match_feedback` values come from the user's grant (never the client). Anything that must forget a user or an event's face data must call `feedback.anonymize_feedback` (retention, consent withdrawal and account deletion already do).
- Pose conventions (server = InsightFace): yaw > 0 = person turned to THEIR left; pitch < 0 = looking down. `frontend/src/lib/face-guidance.ts` flips MediaPipe's pitch/roll to match (calibrated in the browser on identical frames). Re-check if either library is upgraded.
- MediaPipe phones home to `odml.pa.googleapis.com`; keep CSP `connect-src` strict and the fetch guard in `guided-capture.tsx`.
- Security guards were mutation-tested: when you change one, check that a test fails if the guard is removed.
- `rate_limit.client_ip` only trusts `X-Forwarded-For` per `TRUSTED_PROXY_HOPS`; don't read that header elsewhere.
- Opaque tokens (refresh/verify/reset/invite) are stored only as SHA-256 hashes via `services/tokens.py`.

## Conventions

- Next.js 16: middleware is `src/proxy.ts`; `params`/`searchParams` are Promises (server `page.tsx` awaits them and passes plain props to a client component). Check `frontend/node_modules/next/dist/docs/` before using unfamiliar Next APIs.
- Tests use fixtures in `backend/tests/conftest.py` (`make_user`, `login_as`, `make_event`, `add_member`, `mailer`); tables are truncated, Redis flushed and test-bucket objects deleted after each test. Celery runs eagerly (`task_eager_propagates`), so a task's `self.retry` surfaces as `celery.exceptions.Retry`; test exhausted retries by monkeypatching `app.workers.tasks.MAX_RETRIES`.
- Upload tests do real presigned PUTs against SeaweedFS (conftest signs for the internal `S3_ENDPOINT_URL`). When writing binary files from `docker compose exec` for manual testing, don't pipe stdout: InsightFace prints load logs to stdout and corrupts the file. Write to a path and `docker compose cp` it out.
- Selfie tests use `tests/helpers.selfie_set(i)` / `search_as(client, event, i)` (640×480 frames straightened from the group photo). conftest relaxes three selfie limits for these upscaled frames (front yaw 15, side yaw 3, det 0.75); tests of the gate itself set thresholds explicitly.
- Search tests (`tests/test_search.py`) split InsightFace's group photo into left/right halves (3 different people each) and synthesize selfies with `tests/helpers.selfie_of(i)`.
- Frontend camera: `selfie-capture.tsx` uses a generation counter so superseded `getUserMedia` calls stop their own stream (React dev double-mount would otherwise leave the camera on).
- Drive in tests: `drive.set_drive_client(FakeDrive(...))` (`tests/helpers.py`); the real client is tested with googleapiclient's `HttpMockSequence`. Face tests use InsightFace's bundled `t1.jpg` (6 faces) via `tests/helpers.group_photo_bytes()`.
