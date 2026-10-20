# New photo alerts ("new photos since your last scan")

Status: approved by owner 2026-10-20 ("start phase 1").

## Why

Search results are a snapshot. A search writes `search_grants` for the photos that matched and
then throws away the selfie and its embedding (security invariant, `test_selfie_is_never_persisted`,
consent text). Photos synced from Drive or published from guest uploads later are indexed, but the
server has nothing to compare them with, so an attendee who is in them never finds out unless they
happen to scan again. To attendees, it looks like the photos are missing.

This is Part 1 of a two-part plan the owner chose (2026-10-20):

- **Part 1 (this spec):** tell attendees who already searched an event that new photos went live,
  so they scan again. Nothing biometric is stored.
- **Part 2 (separate project, later):** opt-in "keep finding me", which keeps a reference
  embedding with separate explicit consent and matches new photos automatically. Out of scope here.

## Goals

- An attendee who searched an event hears about new photos without opening the app: iOS push +
  email, plus a banner on the event page (web + app) until they scan again.
- One batch of uploads produces one notice, not one per photo.
- Attendees can turn alerts off per event, everywhere (account setting), and with a one-click
  unsubscribe link in each email. Organizers can turn alerts off for their event.

## Non-goals

- No storage of selfies, embeddings or anything derived from them (that is Part 2).
- No photo counts, thumbnails or "you are in N new photos": we don't know whether they are in them.
- No cross-event digest email, no Android, no web push.
- No deploy as part of this work (owner instruction). Pre-deploy checklist: all PRs merged (incl.
  #39), Docker rebuilt from latest main, demo survives a long host sleep.

## Anti-goals (a failure even if it works)

- Any new biometric persistence, or anything that weakens the selfie invariants.
- Notices that leak personal data: names, counts or photos in push payloads (`push.PAYLOAD_KEYS`
  stays as is); counts in emails.
- Spam: more than one push + one email per user per event per 24 h, or alerts after the event's
  photo access has expired.
- Alerting people who never searched, whose membership was revoked/expired, or who opted out.

## Behaviour

### Who is eligible ("subscribers")

A user gets alerts for an event when all of these hold at send time:

- They have completed at least one search of the event (synchronous or overflow queue). Searching
  creates/updates their `event_photo_alerts` row (below). No backfill at launch *(Claude's call,
  owner didn't object)*: people who searched before the release start getting alerts after their
  next search, so nobody is emailed about processing the Privacy Notice didn't mention when they
  searched.
- The per-event toggle is on (default on), and their account-wide `new_photo_alerts` is on
  (default on).
- Membership is still active (`membership.is_active_member`; don't re-implement it).
- The account is active and verified, and the user still has current face consent (re-checked at
  send time like `search_queue` does).
- The event allows it: `events.notify_new_photos` (organizer toggle, default on), the event's
  `access_expires_at` hasn't passed, and retention hasn't run.

### What counts as "new photos"

Published photos with `face_count > 0` whose `published_at` is later than the user's last
notification watermark (the later of `last_searched_at` and `notified_through`). Photos of any source
(Drive, guest upload, organizer upload) count. Faceless photos never trigger alerts.

`photos.published_at` is new: set every time a photo becomes `published`. Today there are exactly
two transitions: `index_photo` (status `processing` → `published`) and moderation approval
(`api/routes/moderation.py`). Route both through one helper so a future path can't miss it.
`reindex-faces` keeps the status and must not bump `published_at`. Existing published rows are backfilled with `indexed_at` (else
`created_at`) in the migration.

### When it's sent (batching)

A beat task (`alerts.new_photos`, every 5 min) looks for events whose newest qualifying photo was
published at least `NEW_PHOTO_ALERT_QUIET_MINUTES` (default 10) ago, i.e. the upload burst has gone
quiet. Note: a Drive sync run is marked `completed` once files are *listed*; indexing finishes later,
photo by photo. That's why the trigger is `published_at`, not sync completion.

For each such event and eligible subscriber with new photos, and whose `last_notified_at` is
older than `NEW_PHOTO_ALERT_MIN_INTERVAL_HOURS` (default 24): send one push and one email, then set
`last_notified_at = now` and `notified_through = newest published_at` included. If a subscriber is
rate-limited, nothing is lost: the next eligible run picks up everything since their watermark.

Ordering: collect recipients and commit the watermarks, then send email + push after the commit
without holding a DB connection (push rule; same pattern as `push.notify_safely`). An at-most-once
send (a crash after commit loses one notice) is acceptable; a duplicate notice is worse.

### Channels

- **Push (iOS):** new `Kind` value `new_photos` in `services/push.py`; payload is the standard
  `payload()` (event_id only, loc-keys `push.new_photos.title/body`, en + de in
  `Localizable.xcstrings`). `PushRouting.swift` opens the event screen.
- **Email:** subject and body say new photos were added to *<event name>* and link to the event page
  to scan again. No counts, no images. Includes the per-event unsubscribe link in the body, plus
  `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers (RFC 8058).
  `core/email.Mail` gets an optional headers field for this. Language *(Claude's call)*: all emails
  today are English-only and users have no locale column; this email picks en/de from the user's
  newest `legal_acceptances.locale` (Accept-Language at Terms acceptance), falling back to English.
  No new `users.locale` column; localizing the other emails is a separate task.
- **Banner:** the member-facing event response (`GET /api/events/{id}`, `EventPublicOut`; the
  route needs the current user + DB added) gets `new_photos_since_last_search: bool` (true when
  qualifying photos exist after `last_searched_at`, independent of the notification
  watermark/toggles). Web event page and iOS event screen show a banner with a "Scan again" action.
  It disappears after the next search.

### Turning it off

- **Per event:** `GET/PUT /api/events/{event_id}/photo-alerts` (`MemberEvent`), body `{enabled}`.
  Toggle on the event page (web + iOS). Shown only once the user has searched (there's no row
  before that).
- **Everywhere:** `users.new_photo_alerts` bool, via the existing `PATCH /api/me/preferences`. Toggle
  in account settings (web + iOS). Does not affect verification/reset/security emails.
- **Email unsubscribe link, no login:** an opaque token via `services/tokens.py` (SHA-256 hash
  stored, new purpose), bound to user + event, valid until the event's access expires (cap 180 days).
  `GET /unsubscribe?token=…` (frontend page) **never** changes anything on GET (link scanners);
  it shows "Stop alerts for this event" and "Stop all new-photo alerts" buttons that POST to
  `POST /api/alerts/unsubscribe {token, scope: "event"|"all"}`. The RFC 8058 one-click POST hits
  the same endpoint, but mail providers send `application/x-www-form-urlencoded`
  `List-Unsubscribe=One-Click` to the header URL, so the endpoint also accepts the token in the
  query string with that form body (scope `event`); GET on that URL does nothing. The endpoint
  never reads auth, is CSRF-exempt only without auth cookies (add a prefix next to
  `WEBHOOK_PREFIX` in `api/csrf.cookieless_app_request`; a logged-in browser still sends
  `X-CSRF-Token` via `lib/api.ts`), and is rate limited per IP (add to `RATE_LIMITED`).
  Invalid/expired token → generic success-looking page (no oracle about accounts).
  Token storage: `auth_tokens` has no `event_id` and `consume_token` is single-use, so add a
  nullable `event_id` (FK CASCADE) plus a new `TokenKind`, or a small dedicated table, hashed via
  `services/tokens.py` either way; the token must stay usable for "event" then "all" (builder's
  choice how).
- **Organizer:** `events.notify_new_photos` bool (default true) in the event settings schema + UI,
  next to `auto_publish_faceless_photos`.

## Data model

- `photos.published_at timestamptz NULL` + index `(event_id, published_at)` (declare on the model
  too, `test_migrations.py`).
- `users.new_photo_alerts bool NOT NULL DEFAULT true`.
- `events.notify_new_photos bool NOT NULL DEFAULT true`.
- New `event_photo_alerts`: `user_id` + `event_id` (PK, both FK CASCADE), `enabled bool default
  true`, `last_searched_at`, `notified_through NULL`, `last_notified_at NULL`. Not biometric, but it
  records that a user searched an event, so it's personal data and is deleted with the rest:
  - `retention.expire_event` deletes the event's rows (and unsubscribe tokens);
  - consent withdrawal and `account.delete_account` delete the user's rows and tokens;
  - member removal/revocation: rows can stay (eligibility re-checks membership), but deleting them
    is fine too; builder's call.
- Hand-written Alembic migration `NNNN_new_photo_alerts.py`.

## Legal / GDPR

- The Privacy Notice (en + de, `services/legal.py`) needs a sentence about new-photo alert emails
  and pushes (purpose, legal basis Art. 6(1)(b)/(f), how to opt out) and the new
  `event_photo_alerts` record. That's a `VERSIONS["privacy"]` bump + new pinned hash in
  `test_legal.py`. **Wording goes in the counsel-review queue**, along with the other open legal
  items.
- Privacy-only bump *(Claude's call)*: it doesn't force re-acceptance (only `terms` and
  `organizer-terms` are gated). Whether the Organizer Terms DPA annex also needs a line about
  alerts goes to counsel. If counsel says yes, that's a later `organizer-terms` bump, which sends
  every organizer back through the acceptance gate.
- `event_photo_alerts` records that a user searched an event. The Privacy Notice promises that
  organizers never see searches, so this table must never surface in any organizer or admin view.
- Consent text (`FACE_CONSENT_VERSION`) does **not** change: nothing biometric is stored.
- No new cookie.

## Security invariants to keep green

- `test_authz_matrix.py`: add the new event-scoped endpoint for cookie + bearer transports; the
  unsubscribe endpoint is unauthenticated by design (token-authorized), so it goes in the matrix as
  public with token checks tested separately.
- Push payload key set unchanged (`PAYLOAD_KEYS`); new kind added to tests.
- Run `python -m app.cli export-openapi` (`test_openapi_contract.py`), then regenerate the iOS client.
- Mutation-check the new guards: membership re-check at send time, opt-out (event / global /
  organizer), expired-access check, token scope/binding, GET-doesn't-unsubscribe, rate limiting.

## Tests (minimum)

Backend: published_at set on every path to published; batching (burst → one notice after the
quiet window; nothing while uploads continue); 24 h cap; watermark (photos before the last search
never alert; rate-limited users get them next time); faceless photos never alert; each opt-out
blocks push and email; revoked/expired member, expired event, retention-run event and withdrawn
consent get nothing; payload/email contain no counts/names beyond the event name in email;
unsubscribe token: hashed at rest, scope event vs all, wrong/expired token, GET is side-effect free,
one-click POST works, rate limited; retention/withdrawal/deletion remove rows + tokens; sends happen
after commit (no connection held).
Frontend: banner, per-event toggle, account toggle, organizer toggle, unsubscribe page (unit + e2e
with Mailpit-captured email in `e2e_server`).
iOS: push routing for `new_photos`, banner + toggle, localisation en/de.

## Left to the builder

- Exact copy for email/push/banner (en + de), within the "no counts" rule.
- Beat interval and the two settings' defaults (10 min quiet, 24 h interval) can be tuned.
- Query shape for the beat task (it must stay cheap across many events: filter events with
  recent `published_at` first).
- Whether member revocation deletes `event_photo_alerts` rows.
