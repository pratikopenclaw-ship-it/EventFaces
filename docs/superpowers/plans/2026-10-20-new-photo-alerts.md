# New Photo Alerts (Part 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attendees who searched an event get one push + one email (and see a banner) when new photos with faces go live there, so they scan again. No biometric data is stored.

**Architecture:** `photos.published_at` marks when a photo went live; each search upserts an `event_photo_alerts` row (user, event, last_searched_at, watermarks, toggle). A 5-minute beat task finds events whose newest qualifying photo is older than a quiet window, picks eligible subscribers, commits watermarks, then sends push (`kind=new_photos`) and email after commit. Opt-outs: per-event toggle, account-wide setting, organizer event setting, token-based one-click unsubscribe.

**Tech Stack:** FastAPI + SQLAlchemy 2 (sync) + Alembic + Celery beat, Postgres, Next.js (client components via `src/lib/api.ts`), SwiftUI iOS app.

**Spec:** `docs/superpowers/specs/2026-10-20-new-photo-alerts-design.md` (read it with this plan).

## Global Constraints

- Nothing biometric is stored: no selfie, embedding or derivative. `FACE_CONSENT_VERSION` does not change.
- Push payloads: only `push.payload(Notice("new_photos", event_id))`; `PAYLOAD_KEYS` unchanged. No names, counts or photos.
- Email: event name + link only. No counts, no images. `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click`.
- Defaults: `NEW_PHOTO_ALERT_QUIET_MINUTES=10`, `NEW_PHOTO_ALERT_MIN_INTERVAL_HOURS=24`, beat every 300 s.
- Only photos with `status == published` and `face_count > 0` count.
- Send after commit, never while holding a DB connection; at-most-once.
- `event_photo_alerts` never appears in any organizer/admin response.
- No backfill: rows are only created by searches made after release.
- Every new endpoint in `tests/test_authz_matrix.py` OPS (cookie + bearer); rate-limited endpoints in `test_endpoint_contracts.py::RATE_LIMITED`; `python -m app.cli export-openapi` after API changes.
- Indexes declared in the migration are also declared on the models.
- Never deploy. Work only in this worktree (`.worktrees/new-photo-alerts`); the dev stack bind-mounts the main checkout and serves the public demo.

## How to run tests from this worktree

The running stack mounts the *main* checkout, so `docker compose exec api pytest` tests the wrong code. From the repo root run the worktree code in a throwaway container on the stack's network (uses the test DB `eventfaces_test`, Redis DB 15 and the test bucket, not demo data):

```bash
docker run --rm --network eventfaces_default --env-file .env \
  -v "$PWD/.worktrees/new-photo-alerts/backend:/app" eventfaces-api pytest -q tests/test_photo_alerts.py
```

Below, `PYTEST <args>` means that command with `pytest -q <args>`. Frontend: `cd .worktrees/new-photo-alerts/frontend && npm ci` once, then the usual lint/typegen/tsc/test commands.

## Review Focus

1. **A burst still uploading at the 10-min mark of its first photo.** Expect no alert until 10 min after the *newest* qualifying photo. Test `test_no_alert_while_burst_continues` (Task 4).
2. **Photo approved by moderation hours after upload.** Expect it to count, with `published_at` = approval time, not upload time. Test `test_moderation_approval_sets_published_at` (Task 1), and `test_moderated_photo_alerts` (Task 4).
3. **User searches again between batch end and beat run.** Expect no alert for photos they already searched over. Test `test_search_after_publish_suppresses_alert` (Task 4).
4. **Email link scanners prefetching the unsubscribe URL.** Expect GET to change nothing. Test `test_unsubscribe_get_has_no_effect` (Task 3).
5. **Revoked or expired attendee, or a withdrawn-consent user, still has a row.** Expect no alert. Tests `test_revoked_member_not_alerted`, `test_withdrawn_consent_not_alerted` (Task 4).

---

### Task 1: `published_at`, alert tables and settings columns

**Files:**
- Create: `backend/alembic/versions/0020_new_photo_alerts.py`, `backend/app/models/photo_alert.py`, `backend/tests/test_photo_alerts.py`
- Modify: `backend/app/models/photo.py` (`published_at` + `Index("ix_photos_event_published", "event_id", "published_at")`), `backend/app/models/user.py` (`new_photo_alerts`), `backend/app/models/event.py` (`notify_new_photos`), `backend/app/models/__init__.py`, `backend/app/services/photo_pipeline.py:244-252`, `backend/app/api/routes/moderation.py:52`

**Interfaces:**
- Produces:
  - `Photo.published_at: datetime | None`; `User.new_photo_alerts: bool` (default True); `Event.notify_new_photos: bool` (default True)
  - `EventPhotoAlert` (`event_photo_alerts`): `user_id`, `event_id` (composite PK, FK CASCADE), `enabled: bool = True`, `last_searched_at: datetime` (not null), `notified_through: datetime | None`, `last_notified_at: datetime | None`
  - `AlertToken` (`alert_tokens`): `token_hash: str(64)` PK, `user_id` FK CASCADE, `event_id` FK CASCADE (indexed), `expires_at`
  - `photo_pipeline.publish(photo: Photo) -> None`: sets `status = published` and `published_at = utcnow()`. The **only** way to publish.

- [ ] **Step 1: Write failing tests** in `tests/test_photo_alerts.py`:
  - `test_index_publishes_with_published_at`: index a photo with faces, then `status == published` and `published_at` is within 5 s of now.
  - `test_moderation_approval_sets_published_at`: a guest upload in `pending_review` is approved via `POST /api/events/{id}/photos/{pid}/moderate {"action":"approve"}`, then `published_at` is set.
  - `test_reindex_keeps_published_at`: re-running `index_photo` on a published photo leaves `published_at` unchanged.
  - `test_only_publish_helper_sets_published`: a static test that greps `backend/app` for `status = PhotoStatus.published` and expects matches only in `photo_pipeline.publish`.
- [ ] **Step 2: Run** `PYTEST tests/test_photo_alerts.py`. Expect FAIL (no attribute `published_at`).
- [ ] **Step 3: Implement** the models, `publish()`, call it in `index_photo` and `moderate`, plus migration 0020 (hand-written). Add the columns with server defaults `true`, create both tables, and backfill `published_at = coalesce(indexed_at, created_at)` for published rows.
- [ ] **Step 4: Run** `PYTEST tests/test_photo_alerts.py tests/test_migrations.py tests/test_guest_uploads.py tests/test_drive_sync.py`. Expect PASS.
- [ ] **Step 5: Commit** `feat(alerts): published_at, alert tables and settings columns`

### Task 2: Subscribe on search; toggles; banner field

**Files:**
- Create: `backend/app/services/photo_alerts.py`, `backend/app/api/routes/photo_alerts.py` (register in `main.py`), `backend/app/schemas/photo_alert.py`
- Modify: `backend/app/services/search.py` (`run_search`, before the final commit), `backend/app/api/routes/events.py:55-57`, `backend/app/schemas/event.py` (`EventPublicOut.new_photos_since_last_search: bool = False`; create/update/admin schemas get `notify_new_photos`, next to `auto_publish_faceless_photos`), `backend/app/schemas/auth.py` (`PreferencesIn.theme` optional + `new_photo_alerts: bool | None = None`; `UserOut.new_photo_alerts`), `backend/app/api/routes/auth.py:226`, `backend/tests/test_authz_matrix.py`, `backend/openapi.json`, `ios/EventFaces/Core/API/openapi.json`

**Interfaces:**
- Consumes: Task 1 models.
- Produces:
  - `photo_alerts.record_search(db: Session, user_id: uuid.UUID, event_id: uuid.UUID, now: datetime) -> None`: upserts the row (`last_searched_at = now`, keeps `enabled`). Does not commit.
  - `photo_alerts.has_new_photos(db, user_id, event_id) -> bool`: true when a published photo with `face_count > 0` has `published_at > last_searched_at`. False with no row.
  - `GET /api/events/{event_id}/photo-alerts` → `PhotoAlertOut {subscribed: bool, enabled: bool}` (`subscribed` = row exists)
  - `PUT /api/events/{event_id}/photo-alerts` body `PhotoAlertIn {enabled: bool}` → `PhotoAlertOut`; 409 `"search_first"` when no row. Both depend on `MemberEvent` + `VerifiedUser`.

- [ ] **Step 1: Write failing tests:**
  - `test_search_records_subscription` (a fake-engine search creates a row with `last_searched_at` ≈ now; a second search updates it and keeps `enabled=False` if it was off).
  - `test_banner_flag` (false before any new photo; true after a photo publishes later; false after searching again).
  - `test_toggle_requires_prior_search` (409).
  - `test_toggle_roundtrip`.
  - `test_preferences_new_photo_alerts` (PATCH with only `new_photo_alerts`; theme cookie untouched when `theme` is omitted).
  - `test_admin_event_out_has_no_alert_rows`: `EventAdminOut` and the members list carry no `last_searched_at`/alert fields.
  - `test_organizer_can_disable_notify_new_photos`.
  - Add both new ops to `OPS` as `"MEMBER"`.
- [ ] **Step 2: Run** `PYTEST tests/test_photo_alerts.py tests/test_authz_matrix.py`. Expect FAIL.
- [ ] **Step 3: Implement.** In `get_event`, add `user: VerifiedUser, db: DB` and return the event plus the flag. Call `record_search` in `run_search` after the audit flush.
- [ ] **Step 4: Run** `PYTEST tests/test_photo_alerts.py tests/test_authz_matrix.py tests/test_search.py tests/test_search_queue.py tests/test_theme.py`, then export OpenAPI (`docker run … eventfaces-api python -m app.cli export-openapi`), copy it to `ios/EventFaces/Core/API/openapi.json`, and `PYTEST tests/test_openapi_contract.py`. Expect PASS.
- [ ] **Step 5: Commit** `feat(alerts): subscribe on search, per-event/account/organizer toggles, banner flag`

### Task 3: Unsubscribe tokens and endpoint

**Files:**
- Modify: `backend/app/services/tokens.py`, `backend/app/api/csrf.py`, `backend/app/api/routes/photo_alerts.py`, `backend/tests/test_endpoint_contracts.py`, `backend/tests/test_authz_matrix.py`, `backend/tests/test_photo_alerts.py`

**Interfaces:**
- Produces:
  - `tokens.issue_alert_token(db, user_id, event_id, expires_at: datetime) -> str` (stores `hash_token(raw)` only)
  - `tokens.find_alert_token(db, raw: str) -> AlertToken | None` (unexpired; reusable, not consumed)
  - `POST /api/alerts/unsubscribe`:
    - JSON `{token: str, scope: "event"|"all"}`, **or** a form body `List-Unsubscribe=One-Click` with `?token=` (scope `event`).
    - Always 200 `{"detail": "ok"}`, even for bad tokens.
    - Rate limited: `rate_limit.enforce(f"alerts-unsub:{client_ip}", Limit(30, 3600))`.
  - `csrf.ALERTS_UNSUBSCRIBE_PREFIX = "/api/alerts/unsubscribe"`, added to `cookieless_app_request`.
  - Token expiry: `min(event.access_expires_at, now + 180 days)` (180 days if no access end).

- [ ] **Step 1: Write failing tests:**
  - `test_unsubscribe_event_scope`.
  - `test_unsubscribe_all_scope` (sets `users.new_photo_alerts=False`).
  - `test_one_click_form_post`.
  - `test_bad_or_expired_token_looks_ok_and_changes_nothing`.
  - `test_token_hashed_at_rest` (the raw value is not in `alert_tokens`).
  - `test_unsubscribe_get_has_no_effect` (GET on the URL → 405, row still enabled).
  - `test_unsubscribe_without_cookie_skips_csrf`, `test_unsubscribe_with_cookie_needs_csrf`.
  - Add the op to `OPS` as `"PUBLIC"` and to `RATE_LIMITED`.
- [ ] **Step 2: Run** `PYTEST tests/test_photo_alerts.py tests/test_endpoint_contracts.py tests/test_authz_matrix.py`. Expect FAIL.
- [ ] **Step 3: Implement.** Read the body raw so both content types are accepted.
- [ ] **Step 4: Run** the same command, plus the OpenAPI export + contract test. Expect PASS. Mutation-check: drop the CSRF prefix or the rate-limit line and confirm a test fails.
- [ ] **Step 5: Commit** `feat(alerts): one-click unsubscribe tokens`

### Task 4: Alert sender (beat task, push, email)

**Files:**
- Modify: `backend/app/services/photo_alerts.py`, `backend/app/services/push.py` (`Kind` += `"new_photos"`), `backend/app/core/email.py` (`Mail.headers: tuple[tuple[str, str], ...] = ()`, applied in `build_message` through `_one_line`), `backend/app/core/config.py` (the two settings), `backend/app/workers/tasks.py` (`alerts.new_photos`), `backend/app/workers/celery_app.py` (`"new-photo-alerts": {"task": "alerts.new_photos", "schedule": 300.0}`), `backend/tests/test_photo_alerts.py`, `backend/tests/test_push.py`

**Interfaces:**
- Consumes: Tasks 1–3 (`issue_alert_token`).
- Produces:
  - `photo_alerts.collect_due(db, now: datetime) -> list[PendingAlert]`:
    - Locks and updates watermarks (`last_notified_at = now`, `notified_through = newest published_at`), then commits.
    - `PendingAlert(user_id, event_id, email, event_name, locale: "en"|"de", unsubscribe_token)` is a frozen dataclass.
  - `photo_alerts.deliver(alerts: list[PendingAlert]) -> None`: no DB use; email via `get_mailer()` (failures logged by type only); push via `push.notify_safely`, grouped by event.
  - `photo_alerts.run(db, now) -> int`: `deliver(collect_due(db, now))`, returns the count.
  - Eligibility: everything in the spec's "Who is eligible", via `membership.is_active_member`, `face_consent_version == FACE_CONSENT_VERSION`, active + verified user, `event.notify_new_photos`, the event's access not ended and retention not run, the row enabled, `user.new_photo_alerts`, `last_notified_at` older than the interval, and qualifying photos after `max(last_searched_at, notified_through)` whose newest `published_at <= now - quiet`.
  - Locale: the newest `LegalAcceptance.locale` starting with `de` → `"de"`, else `"en"`.
  - Email: subject en `New photos from {event}` / de `Neue Fotos von {event}`. The body has the event link `{FRONTEND_URL}/events/{id}` and the unsubscribe link `{FRONTEND_URL}/unsubscribe?token=…`. Headers: `List-Unsubscribe: <{FRONTEND_URL}/api/alerts/unsubscribe?token=…>`, `List-Unsubscribe-Post: List-Unsubscribe=One-Click`.

- [ ] **Step 1: Write failing tests** (use the captured mailer and fake push transport as in `test_search_queue.py`/`test_push.py`, and pass `now` explicitly):
  - `test_burst_sends_one_alert_after_quiet_window`.
  - `test_no_alert_while_burst_continues`.
  - `test_faceless_photos_never_alert`.
  - `test_photos_before_last_search_never_alert`.
  - `test_search_after_publish_suppresses_alert`.
  - `test_moderated_photo_alerts`.
  - `test_24h_cap_then_catch_up` (a second batch inside 24 h → nothing; after 24 h → one alert covering it).
  - `test_event_toggle_off`, `test_account_toggle_off`, `test_organizer_toggle_off`.
  - `test_revoked_member_not_alerted`, `test_expired_access_not_alerted`, `test_retention_run_not_alerted`, `test_withdrawn_consent_not_alerted`.
  - `test_push_payload_is_generic` (keys == `PAYLOAD_KEYS`, kind `new_photos`).
  - `test_email_has_no_counts_and_has_unsubscribe_headers`.
  - `test_german_email_for_de_acceptance`.
  - `test_deliver_holds_no_connection` (pattern from `test_pool_starvation.py`).
- [ ] **Step 2: Run** `PYTEST tests/test_photo_alerts.py tests/test_push.py`. Expect FAIL.
- [ ] **Step 3: Implement.** Keep `collect_due` cheap: first `select distinct event_id` from photos with `published_at > now - 7 days` and `face_count > 0`, then evaluate subscribers per event.
- [ ] **Step 4: Run** `PYTEST tests/test_photo_alerts.py tests/test_push.py tests/test_pool_starvation.py tests/test_contact.py`. Expect PASS. Mutation-check each eligibility guard (comment it out → a test fails).
- [ ] **Step 5: Commit** `feat(alerts): batched new-photo push + email`

### Task 5: Forgetting (retention, consent withdrawal, account deletion)

**Files:**
- Modify: `backend/app/services/retention.py:65-91`, `backend/app/api/routes/search.py:89-97`, `backend/app/services/account.py:56-62`, `backend/tests/test_photo_alerts.py`

- [ ] **Step 1: Write failing tests:**
  - `test_retention_deletes_alert_rows_and_tokens`.
  - `test_withdrawal_deletes_user_alert_rows_and_tokens`.
  - `test_account_deletion_deletes_alert_rows_and_tokens` (explicit deletes, not only CASCADE).
- [ ] **Step 2: Run.** Expect FAIL for retention and withdrawal.
- [ ] **Step 3: Implement** `photo_alerts.forget_event(db, event_id)` and `photo_alerts.forget_user(db, user_id)` (delete rows + tokens, no commit) and call them in the three places.
- [ ] **Step 4: Run** `PYTEST tests/test_photo_alerts.py tests/test_retention.py tests/test_gdpr.py tests/test_privacy.py`. Expect PASS.
- [ ] **Step 5: Commit** `feat(alerts): delete alert data with event retention, consent withdrawal and account deletion`

### Task 6: Privacy Notice update

**Files:** `backend/app/services/legal.py` (privacy en + de, `VERSIONS["privacy"] = "2026-10-20"`), `backend/tests/test_legal.py` (new pinned hash)

- [ ] **Step 1:** In both languages, add to the privacy section that covers notifications/devices: after a search we remember that you searched the event (to tell you about new photos), and we send at most one email and one push per event per day when new photos are added, with no counts or photos. Legal basis Art. 6(1)(b)/(f). You can turn alerts off per event, in Settings, or with the link in each email. The record is deleted with the event's face data, on withdrawal of face consent, or with your account. Add the retention line to the storage-periods paragraph.
- [ ] **Step 2: Run** `PYTEST tests/test_legal.py`. Expect FAIL (hash). Update the pin, run again, expect PASS.
- [ ] **Step 3: Commit** `docs(legal): privacy notice covers new-photo alerts`. Note in the PR that the wording needs counsel review, and that the question of a line in the DPA annex is open.

### Task 7: Web UI

**Files:**
- Create: `frontend/src/app/events/[id]/photo-alerts.tsx`, `frontend/src/app/unsubscribe/page.tsx`, `frontend/e2e/photo-alerts.spec.ts`
- Modify: `frontend/src/app/events/[id]/page.tsx`, `frontend/src/app/account/page.tsx`, `frontend/src/components/event-form.tsx`, `frontend/src/lib/types.ts`, `backend/tests/e2e_server.py` (a `/__e2e/run-photo-alerts` control endpoint that calls `photo_alerts.run` with `now` advanced past the quiet window)

- [ ] **Step 1: Write the e2e test** `photo-alerts.spec.ts`. An attendee (`@example.com`) searches, then the organizer adds a photo with a face via the fake Drive + sync. Then:
  - the banner "New photos were added since your last scan" is visible with a "Scan again" button;
  - `/__e2e/run-photo-alerts` → Mailpit-captured email contains the event name and the unsubscribe link;
  - opening the link shows two buttons and doesn't change anything until one is clicked; "Stop alerts for this event" → the event toggle shows off;
  - the account toggle and the organizer `notify_new_photos` checkbox persist.
- [ ] **Step 2: Run** `docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api web` (from the worktree, with the main stack's api/web stopped), then `npx playwright test e2e/photo-alerts.spec.ts`. Expect FAIL. ⚠ This stops the demo's api/web: ask the user before running it.
- [ ] **Step 3: Implement.** Use token classes only (`bg-accent text-on-accent`, etc.). The banner and toggle render only when `subscribed`.
- [ ] **Step 4: Run** `npm run lint && npx next typegen && npx tsc --noEmit && npm run build`, then the spec, plus `e2e/a11y.spec.ts`, `e2e/theme.spec.ts`. Expect PASS. Then `docker compose up -d api` to switch back.
- [ ] **Step 5: Commit** `feat(alerts): web banner, toggles and unsubscribe page`

### Task 8: iOS

**Files:** `ios/EventFaces/Core/Push/PushRouting.swift` (`kinds` += `"new_photos"` → `.event(eventID:)`, or the existing event route), `ios/EventFaces/Features/Event/*` (banner + toggle), `ios/EventFaces/Features/Settings/*` (account toggle), `ios/EventFaces/Resources/Localizable.xcstrings` (`push.new_photos.title/body` + UI strings, en + de), tests in `ios/EventFacesTests`

- [ ] **Step 1: Write failing tests:** a push-routing unit test for `new_photos`, a view-model test for the banner/toggle visibility rules, and a localisation completeness check (it already exists, so extend it).
- [ ] **Step 2:** `ios/scripts/bootstrap.sh`, then `ios/scripts/test.sh`. Expect FAIL.
- [ ] **Step 3: Implement** using the regenerated API client from Task 2/3. Colours only from the asset catalog.
- [ ] **Step 4:** `ios/scripts/test.sh` (iPhone + iPad). Expect PASS.
- [ ] **Step 5: Commit** `feat(ios): new-photo alert push routing, banner and toggles`

### Finish

- [ ] Full backend suite `PYTEST` (in the worktree), frontend checks, `scripts/security-scan.sh` (18/18 PASS), then open the PR. **No deploy.**
