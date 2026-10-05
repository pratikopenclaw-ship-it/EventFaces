# Deploying EventFaces (EU)

Target: **one Hetzner Cloud server in Germany** running `docker-compose.prod.yml` (Caddy for TLS,
Next.js, FastAPI, Celery worker and beat, Postgres + pgvector, Redis, and GlitchTip for error
reports, uptime and heartbeat alerts on `errors.<domain>`), with photos in **Cloudflare R2
(EU jurisdiction)** and email through any SMTP relay. All processing and storage stay in the EU.

Read this once end to end before starting. Commands assume Ubuntu 24.04, a domain you control
(`photos.example.org` below), and that you run them from your laptop unless marked **(server)**.

> Face embeddings are biometric data (GDPR Art. 9). Section 0 is not optional.

## 0. Before any infrastructure (legal and organisational)

1. Complete a **DPIA** (Art. 35) for face search. The privacy notice (`/privacy`), consent text and
   retention table in the README are your inputs.
2. Sign **DPAs** with every processor: Hetzner (hosting), Cloudflare (R2), your email provider, and
   Google if you use Drive import. Keep them with your records of processing (Art. 30).
3. Name a **security contact** and a **privacy contact**, and decide who answers access and erasure
   requests (the app handles erasure itself; data export is manual, see report R-6).
4. Have the **legal texts** reviewed and the operator's details filled in (`LEGAL_*` variables;
   production won't start without them). The Terms, Organizer Terms with the data processing
   agreement, Privacy Notice (with its cookie section) and Impressum are served from
   `backend/app/services/legal.py` to web and app. The checklist for your lawyer is in
   **LEGAL_REVIEW.md**.
5. Calibrate the face-match thresholds on **consented** pilot data (see step 10). The shipped
   defaults were validated on synthetic data only.

## 1. Server (Hetzner Cloud)

1. Create a project, then a server:
   - **Location:** Falkenstein (`fsn1`) or Nuremberg (`nbg1`), Germany.
   - **Type:** CCX23 (4 dedicated vCPU, 16 GB RAM) or larger. Face analysis is CPU-bound: each API
     process handles about 0.9 selfie searches per second (see `SECURITY_QA_REPORT.md`, "Load test").
   - **Image:** Ubuntu 24.04. **SSH key only** (no root password). Enable **backups** (Hetzner server
     snapshots, useful for disaster recovery; not a replacement for step 6).
2. Create a **Cloud Firewall** and attach it to the server:
   - Inbound TCP 22 **from your admin IP only**; TCP 80, TCP 443 and **UDP 443** (HTTP/3) from anywhere.
   - No other inbound ports. Postgres and Redis are never published (the compose policy enforces it).
3. **(server)** Base hardening:
   ```bash
   adduser --disabled-password deploy && usermod -aG sudo deploy
   mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && chown -R deploy: /home/deploy/.ssh
   sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/; s/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
   systemctl restart ssh
   apt-get update && apt-get -y upgrade && apt-get -y install unattended-upgrades fail2ban
   dpkg-reconfigure -plow unattended-upgrades
   timedatectl set-timezone UTC
   ```
4. **(server)** Install Docker Engine from Docker's apt repository (docs.docker.com/engine/install/ubuntu),
   then add `deploy` to the `docker` group. Cap container logs so they can't fill the disk:
   ```bash
   cat >/etc/docker/daemon.json <<'EOF'
   { "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "5" } }
   EOF
   systemctl restart docker
   ```

## 2. DNS and TLS

1. At your DNS provider, create `A` (and `AAAA`) records for `photos.example.org` pointing to the
   server's IPv4/IPv6. With Cloudflare DNS, set them to **DNS only** (grey cloud): Caddy terminates
   TLS and replaces `X-Forwarded-For`, which the app trusts with `TRUSTED_PROXY_HOPS=1`. (If you
   later put a proxy or CDN in front, you must configure Caddy's `trusted_proxies` and raise
   `TRUSTED_PROXY_HOPS`, or per-IP rate limits will see only the proxy.)
   Add the same records for `errors.photos.example.org` (GlitchTip, section 8).
2. Add a **CAA** record so only Let's Encrypt can issue for the domain:
   `photos.example.org. CAA 0 issue "letsencrypt.org"` (it covers the `errors.` subdomain too).
3. TLS is automatic: Caddy (`infra/caddy/Caddyfile`) obtains and renews certificates on first start.
   After deployment, verify:
   ```bash
   curl -sI https://photos.example.org | grep -iE "strict-transport|content-security|x-frame"
   ```
   and run an SSL Labs test (target grade A or better).

## 3. Object storage (Cloudflare R2, EU)

1. In Cloudflare, go to **R2**, then **Create bucket**:
   - **Name:** `eventfaces-prod`.
   - **Location:** **Jurisdiction: European Union**. This keeps the data in the EU; it can't be
     changed later.
   - **Public access:** leave it **off**. Don't enable `r2.dev` or a custom public domain: images are
     only ever streamed through the API.
2. **R2 → Manage API tokens → Create API token**: permission **Object Read & Write**, scoped to
   **this bucket only**. Note the access key ID, the secret, and the **EU** S3 endpoint
   (`https://<account-id>.eu.r2.cloudflarestorage.com`).
3. **Bucket → Settings → CORS policy** (browsers upload guest photos straight to R2 with presigned PUTs):
   ```json
   [{ "AllowedOrigins": ["https://photos.example.org"], "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["content-type"], "MaxAgeSeconds": 3600 }]
   ```
   (`python -m app.cli init-storage` tries to set this itself; with a bucket-scoped token it may not
   be allowed to, so set it here.)
4. R2 has no object versioning; photo backups are covered in step 6.

## 4. Email (SPF, DKIM, DMARC)

Use any transactional SMTP relay with EU data processing. Send from a subdomain you control, e.g.
`mail.photos.example.org` or the apex domain.

1. In the provider, **verify the sending domain**. It gives you DNS records; add them exactly:
   - **SPF** (TXT on the sending domain), one record only:
     `v=spf1 include:<provider-spf-domain> -all`
     (if the domain already has SPF, merge the `include:` into it; never publish two SPF records).
   - **DKIM**, usually one or more CNAME/TXT records such as
     `<selector>._domainkey.photos.example.org → <provider value>`.
   - **Return-path / bounce domain**, if the provider offers one (a CNAME), so SPF aligns.
2. **DMARC** (TXT at `_dmarc.photos.example.org`). Start in monitoring mode:
   `v=DMARC1; p=none; rua=mailto:dmarc-reports@example.org; adkim=s; aspf=s; pct=100`
   After 1–2 weeks of clean aggregate reports, tighten to `p=quarantine`, then `p=reject`.
3. Put the SMTP credentials in `.env.prod` (step 5): `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_TLS=true`,
   `SMTP_USER`, `SMTP_PASSWORD`, and `EMAIL_FROM="EventFaces <no-reply@photos.example.org>"` (the
   From domain must be the verified one).
4. Verify: send yourself a password-reset email and check the headers show `spf=pass`, `dkim=pass`,
   `dmarc=pass` (Gmail: "Show original"). Aim for 10/10 at mail-tester.com.

## 5. Secrets and configuration

1. **(server)** as `deploy`: `git clone` the repository at a **release tag**, then
   `cp .env.example .env.prod && chmod 600 .env.prod`. `.env.prod` is git-ignored; never commit it.
2. Generate every secret separately (store them in your password manager or secret store as well):
   ```bash
   for n in JWT_SECRET DOWNLOAD_TOKEN_SECRET POSTGRES_PASSWORD APP_DB_PASSWORD REDIS_PASSWORD \
            GLITCHTIP_SECRET_KEY GLITCHTIP_DB_PASSWORD PAYMENTS_WEBHOOK_SECRET; do
     echo "$n=$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48)"; done
   ```
3. Set in `.env.prod`:
   - `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `DOMAIN=photos.example.org`,
     `FRONTEND_URL=https://photos.example.org`, `TRUSTED_PROXY_HOPS=1`
   - `JWT_SECRET`, `DOWNLOAD_TOKEN_SECRET` (two different values)
   - `POSTGRES_USER=eventfaces`, `POSTGRES_PASSWORD`, `POSTGRES_DB=eventfaces`, `APP_DB_PASSWORD`
   - `DATABASE_URL=postgresql+psycopg://eventfaces_app:<APP_DB_PASSWORD>@db:5432/eventfaces`
   - `MIGRATION_DATABASE_URL=postgresql+psycopg://eventfaces:<POSTGRES_PASSWORD>@db:5432/eventfaces`
   - `REDIS_PASSWORD` and `REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0`
   - `S3_ENDPOINT_URL` and `S3_PUBLIC_ENDPOINT_URL` = the R2 EU endpoint, `S3_REGION=auto`,
     `S3_BUCKET=eventfaces-prod`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
   - `SMTP_*`, `EMAIL_FROM` (step 4); `GOOGLE_SERVICE_ACCOUNT_JSON` if you use Drive import
   - `GLITCHTIP_SECRET_KEY`, `GLITCHTIP_DB_PASSWORD`; `GLITCHTIP_EMAIL_URL`
     (`smtp://user:password@host:587`) and `GLITCHTIP_FROM_EMAIL` for its alert emails
   - `SENTRY_DSN` and `WEB_SENTRY_DSN`: set after GlitchTip's first start (section 6)
   - `RETENTION_HEARTBEAT_URL`, `DISK_HEARTBEAT_URL`: heartbeat check-in URLs (section 8)
   - `CONTACT_EMAIL`: where the landing page's contact form is sent (defaults to `LEGAL_EMAIL`;
     messages are emailed with Reply-To set to the sender and never stored)
   - Payments: `PAYMENTS_WEBHOOK_SECRET`, and for **UAT only** `ALLOW_TEST_PAYMENTS=true`. Only the
     fake (TEST MODE) provider exists so far: production refuses to start with it unless this flag
     is set, and every billing page then shows a test-mode banner. Remove the flag when a real
     provider is configured.
   - Remove every `TEST_*` variable.
4. The API **refuses to start** in production if a value is still a development or public default
   (dev or low-entropy secrets, equal JWT and download secrets, insecure cookies, a non-https frontend,
   the owner role or a dev password in `DATABASE_URL`, Redis without a private password, the dev S3
   key, Mailpit as SMTP, a missing or plaintext-over-the-internet `SENTRY_DSN`, weak GlitchTip
   secrets, a weak `PAYMENTS_WEBHOOK_SECRET`, or the test payment provider without
   `ALLOW_TEST_PAYMENTS=true`). The error lists every problem.
5. **Rotation** (at least yearly, and immediately after a suspected leak or a staff change):

   | Secret | How | Effect |
   |---|---|---|
   | `JWT_SECRET` | New value, restart `api` | Everyone is logged out |
   | `DOWNLOAD_TOKEN_SECRET` | New value, restart `api` | Download links (2-minute life) stop working |
   | `APP_DB_PASSWORD` | `ALTER ROLE eventfaces_app PASSWORD '…'` as the owner, update `.env.prod`, restart `api`, `worker`, `beat` | None |
   | `POSTGRES_PASSWORD` | `ALTER ROLE eventfaces PASSWORD '…'`, update `.env.prod` | Used only by migrations |
   | `REDIS_PASSWORD` | Update `.env.prod`, restart `redis`, `api`, `worker`, `beat` | Rate-limit counters and queued-search statuses reset |
   | `PAYMENTS_WEBHOOK_SECRET` | New value, restart `api` (with a real provider: rotate it there too) | Confirmations signed with the old secret are refused (a real provider retries them) |
   | `GLITCHTIP_DB_PASSWORD` | Update `.env.prod`, run `scripts/glitchtip-db.sh`, restart `glitchtip` | None |
   | `GLITCHTIP_SECRET_KEY` | Update `.env.prod`, restart `glitchtip` | GlitchTip users are logged out |
   | GlitchTip DSN keys | Create a new key on the project, update `SENTRY_DSN`/`WEB_SENTRY_DSN`, redeploy, then delete the old key | None |
   | R2 / SMTP / Google keys | Create a new key at the provider, update `.env.prod`, restart, then revoke the old key | None |

## 6. Deploy

Releases are tags made with `scripts/release.sh` (section 9). **First deploy (server)**, from the
repository directory, in this order (the API refuses to start without a working `SENTRY_DSN`):
```bash
C="docker compose -f docker-compose.prod.yml --env-file .env.prod"
git fetch --tags && git checkout v1.0.0-rc.1
$C up -d db && scripts/glitchtip-db.sh                 # GlitchTip's own role and database
$C up -d glitchtip caddy                                 # errors.photos.example.org
$C exec glitchtip ./manage.py createsuperuser            # your GlitchTip login (sign-up is off)
```
In GlitchTip (`https://errors.photos.example.org`): create the organization, then two projects,
`api` (Python) and `web` (JavaScript). Put their DSNs in `.env.prod` **with the internal host**
so keys never leave the server: `SENTRY_DSN=http://<api key>@glitchtip:8000/<api project id>`,
`WEB_SENTRY_DSN=http://<web key>@glitchtip:8000/<web project id>`. Then:
```bash
scripts/deploy.sh v1.0.0-rc.1                            # backup, build, start, release check
$C exec api python -m app.cli create-superadmin --email you@example.org
```
Then smoke test: log in, create an event, upload a photo as a guest, search with your own face,
download it, and delete the test event.

**Tuning**, in `.env.prod`, then restart `api`:
- `SEARCH_MAX_CONCURRENT` (default 6 per API process): searches admitted at once. Size it as
  throughput × acceptable wait.
- `SEARCH_OVERFLOW_QUEUE_SIZE` (default 20): busy searches queued in memory, with an email when done.
- `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` (10/20 per process). Postgres allows 200 connections in the
  production compose file.
- `PASSWORD_HASH_MAX_CONCURRENT` (4): Argon2 hashes at once (~64 MB each).
- More capacity means a bigger server, or more `--workers` in the `api` command (each process uses
  ~1 GB with the face model loaded).

## 7. Backups and restore

**What to back up:**

| Data | Where | How |
|---|---|---|
| Database (accounts, events, embeddings, grants, audit) | Postgres volume | Nightly `pg_dump -Fc`, encrypted, off-site |
| Photos | R2 bucket (originals also still in the organizers' Drive folders) | Nightly `rclone sync` to a second EU location |
| Redis | Rate limits, capture tokens, queued-search statuses | **Not backed up** (all short-lived) |
| `.env.prod` | Server | In your secret store (never in the backup bucket in plain text) |

**Retention:** backups contain face embeddings. Keep database backups for **at most 30 days**, so
erased or expired data leaves the backups within 30 days. Say so in the privacy notice.

**Nightly database backup** with [restic](https://restic.net) (encrypted) to a Hetzner Storage Box
(Germany). **(server)**, as root:
```bash
apt-get -y install restic
export RESTIC_REPOSITORY=sftp:u123456@u123456.your-storagebox.de:eventfaces-db
export RESTIC_PASSWORD_FILE=/root/.restic-pass     # a long random passphrase, also in your secret store
restic init
cat >/etc/cron.daily/eventfaces-db-backup <<'EOF'
#!/bin/sh
set -e
export RESTIC_REPOSITORY=sftp:u123456@u123456.your-storagebox.de:eventfaces-db RESTIC_PASSWORD_FILE=/root/.restic-pass
cd /home/deploy/EventFaces
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db pg_dump -U eventfaces -Fc eventfaces \
  | restic backup --stdin --stdin-filename eventfaces.dump --tag db
restic forget --tag db --keep-daily 30 --prune
# Check in with the "backup" heartbeat monitor (section 8); only reached when everything above succeeded.
curl -fsS -m 10 -X POST -o /dev/null "https://errors.photos.example.org/api/0/organizations/<org>/heartbeat_check/<id>/"
EOF
chmod 700 /etc/cron.daily/eventfaces-db-backup
```
**Photos:** `rclone sync r2:eventfaces-prod storagebox:eventfaces-photos` nightly, using an rclone
`crypt` remote on the Storage Box side (encrypted at rest). Keep 30 days.

**Restore procedure** (practice it quarterly; `scripts/backup_restore_drill.sh` automates the
verification part locally):
1. `restic snapshots --tag db`, then pick the snapshot and run
   `restic dump <id> eventfaces.dump > /tmp/eventfaces.dump`.
2. Stop the app: `docker compose … stop api worker beat`.
3. `docker compose … exec -T db psql -U eventfaces -d postgres -c "DROP DATABASE eventfaces WITH (FORCE)" -c "CREATE DATABASE eventfaces"`
4. `docker compose … exec -T db pg_restore -U eventfaces -d eventfaces --exit-on-error < /tmp/eventfaces.dump`, then `shred -u /tmp/eventfaces.dump`.
5. `docker compose … up -d`. Check `/api/health`, log in, and confirm an event's photos and search work.
6. **Re-apply erasures**: account or event deletions made after the backup was taken must be repeated
   (keep a log of erasure requests for exactly this).

## 8. Monitoring and alerting

Self-hosted **GlitchTip** (Sentry protocol, `errors.photos.example.org`, same server, so no new
processor) receives error reports and runs uptime and heartbeat monitors.

**What is reported, and what never is.** API and Celery errors (`app/core/monitoring.py`), web
server errors (`src/instrumentation.ts`) and browser errors (through the same-origin tunnel
`/monitoring`, so the CSP stays first-party). Reports carry the error type, a redacted message
and stack, the page path and the opaque user id. They never carry request bodies (selfies),
cookies, auth headers, query strings, local variables, emails or tokens in URLs; tests and a
mutation check enforce this (`tests/test_monitoring.py`, `src/lib/error-report.test.ts`,
`e2e/monitoring.spec.ts`). GlitchTip keeps reports for **30 days**. The iOS app has no SDK: use
App Store Connect / Xcode Organizer crash reports (symbolicated, opt-in by users).

**Set up once in GlitchTip** (organization settings):
1. **Alerts:** on both projects, an alert rule "new or regressed issue" that emails the ops address
   (set `GLITCHTIP_EMAIL_URL` / `GLITCHTIP_FROM_EMAIL`).
2. **Uptime monitors** (every 60 s, alert after 2 failures): `https://photos.example.org/api/health`
   (expects 200), and `https://photos.example.org/` (expects 200). GlitchTip runs on the same
   server, so also add one external check (for example a free EU uptime service, or Uptime Kuma
   on another host) on `/api/health`: it is the only alert that fires if the whole server is down.
   Alert on TLS certificate expiry below 14 days there too.
3. **Heartbeat monitors** (GlitchTip alerts when check-ins stop):

   | Monitor | Expected every | Pinged by | Setting |
   |---|---|---|---|
   | retention | 65 min | the hourly retention job, after a successful run (a GDPR duty) | `RETENTION_HEARTBEAT_URL` in `.env.prod`, restart `worker` |
   | backup | 25 h | the nightly backup script, after `restic` succeeds | `curl -fsS -m 10 -X POST <url>` as its last line (section 7) |
   | disk | 15 min | `scripts/disk-check.sh` from cron, only while disk < 80% and memory < 90% | `DISK_HEARTBEAT_URL` in `.env.prod` |

   For the containers, use the internal URL (`http://glitchtip:8000/api/0/organizations/<org>/heartbeat_check/<id>/`);
   for host cron jobs, the public one on `errors.photos.example.org`. The disk check:
   `echo "*/10 * * * * deploy /home/deploy/EventFaces/scripts/disk-check.sh" | sudo tee /etc/cron.d/eventfaces-disk`.
4. **Test every alert once** before go-live and note the date: stop `api` for 3 minutes (uptime);
   `docker compose … exec api python -c "import sentry_sdk; from app.core import monitoring; monitoring.init('api'); sentry_sdk.capture_message('alert test'); sentry_sdk.flush()"`
   (new issue); stop `beat` for 70 minutes (retention); `DISK_MAX_PERCENT=1 scripts/disk-check.sh` for 20 minutes (disk);
   skip one backup night or point the backup heartbeat at a fresh monitor (backup).

**Still from logs / the host** (`docker compose … logs api`):
- **503 rate** (search busy, queue full, hashing busy or pool busy) is the capacity signal: sustained
  503s mean it's time to add processes or a bigger server.
- `Refusing to start in production` (a configuration error on deploy; `deploy.sh` rolls back).
- Celery backlog: `docker compose … exec redis redis-cli -a "$REDIS_PASSWORD" LLEN celery` and
  `LLEN index` > 500 for 30 minutes.
- **Logs:** Docker keeps 5 × 50 MB per container (step 1). If you ship logs elsewhere, keep them
  for 30–90 days: they contain IP addresses and user IDs (never selfies or embeddings). Keep Caddy
  access logging off, or apply the same token redaction as `app/core/logging.RedactTokens`.

## 9. Releases, deploys and rollbacks

**CI** (`.github/workflows/ci.yml`) runs on every pull request and push to `main`: backend tests,
web lint/types/unit tests/build, Playwright in all five browser projects, and the security scan.
iOS unit tests run on demand (Actions → CI → Run workflow → "iOS"); the full iOS gate
(`ios/scripts/test.sh`, needs the e2e API) and the visual baselines (`e2e/visual.spec.ts`, macOS
fonts) stay local release checks. Protect `main` so pull requests need the CI checks to pass.

**Release** (laptop, on an up-to-date `main` whose CI passed):
```bash
scripts/release.sh v1.0.0-rc.1      # UAT builds: -rc.N (GitHub pre-release); production: v1.0.0
```
It refuses unless `main` is clean and equal to `origin/main` and CI passed on that commit, then
creates an annotated tag with notes from the merged pull requests, pushes it and creates the
GitHub release.

**Deploy** (server): `scripts/deploy.sh v1.0.0-rc.1`. It
1. checks the tag and a clean checkout;
2. dumps the database to `.deploy/predeploy-<time>-<previous tag>.dump` (mode 600; the newest 3
   are kept, older ones are shredded: they contain face embeddings);
3. checks out the tag, builds the images with `APP_VERSION=<tag>`, starts them (the API migrates
   on start) and waits until every service is healthy;
4. runs `scripts/release_check.sh` (health and version, TLS and certificate expiry, HTTP→HTTPS,
   CSP/HSTS/frame headers, cookie flags, the legal pages without placeholders, API docs off, the
   error tunnel, the Universal Links file, GlitchTip up).

**On any failure it rolls back by itself** to the previous release: a schema change is undone
with `alembic downgrade` using the new release's migrations (keeps data written since the
deploy); if that fails, the database is restored from step 2's dump (anything written during the
deploy is lost). Then the previous tag is built, started and checked again. History is in
`.deploy/history`.

**Manual rollback** (for example a bug found an hour later): `scripts/rollback.sh` (to the release
before the current one) or `scripts/rollback.sh v1.0.0-rc.1`. After a rollback it asks for an
explicit tag rather than guessing. Rebuild images at least monthly to pick up base-image fixes.

The whole cycle (first deploy, failed deploy with auto-rollback, good deploy, manual rollback,
failed downgrade with restore) was rehearsed on the production compose file locally (see
SECURITY_QA_REPORT.md).

## 9a. iOS app (backend side)

The API serves the iOS app with no extra services. Set these in `.env.prod` when the app ships:

- **Universal Links:** `APPLE_TEAM_ID` and `IOS_BUNDLE_ID`. The web container then serves `/.well-known/apple-app-site-association` (JSON, no redirect; join, invite, sign-in and event links open the app; admin and API paths never do). Check with `curl -sI https://<domain>/.well-known/apple-app-site-association` and Apple's validator after the first TestFlight build.
- **Push (APNs):** create a token-based key (`.p8`) in the Apple Developer portal, then set `APNS_KEY_P8` (the PEM contents), `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC` (the bundle id) and `APNS_ENV=production`. Store the key in the secret store like the other secrets; the production guard refuses a malformed key. Notifications carry only a localization key and ids (no names, photos or counts).
- **App Attest (report-only):** set `APP_ATTEST_APP_ID` to `<Team ID>.<bundle id>` and `APP_ATTEST_ENV=production` (the production guard refuses development keys). The app then attests a fresh key after each sign-in and adds an assertion to every refresh; results are stored on the device row (`attest_status`/`attest_reason`, `assertion_status`/`assertion_reason`) and logged as reason codes, and **never block a request**. Review them with `docker compose exec api python -m app.cli attest-report` after the first TestFlight builds. Enforcing is a separate, later change once real installs pass.
- **Forced updates:** after a security fix in the app, raise `IOS_MIN_SUPPORTED_VERSION`; older apps then get "update required" (HTTP 426) with `IOS_UPDATE_URL`.
- **Sign-in codes** arrive by the same email setup as verification mails (section 4): check that the "is your EventFaces code" mail passes SPF/DKIM/DMARC.

## 10. Go / no-go checklist

Launch only when every box is ticked.

**Legal and privacy**
- [ ] DPIA completed and signed off; DPAs in place with Hetzner, Cloudflare, the email provider (and Google if Drive is used)
- [ ] Privacy notice reviewed; the backup retention (≤ 30 days) is stated; security and privacy contacts published (`/.well-known/security.txt`)
- [ ] Face-match thresholds calibrated on consented pilot data (`FACE_MATCH_THRESHOLD`, `MATCH_BEST_THRESHOLD`)

**Infrastructure**
- [ ] Server in Germany, firewall allows only 22 (admin IP), 80, 443/tcp and 443/udp; root login and passwords disabled
- [ ] DNS A/AAAA and CAA records; HTTPS works; SSL Labs grade ≥ A; HSTS, CSP and X-Frame-Options present
- [ ] R2 bucket in the **EU jurisdiction**, not public, token scoped to the bucket, CORS limited to the domain
- [ ] `.env.prod` is mode 600, every secret unique and random, stored in the secret store; the API starts (production guard passed)

**Email**
- [ ] SPF, DKIM and DMARC records published; a test email shows spf/dkim/dmarc = pass; DMARC reports are arriving

**Data safety**
- [ ] The nightly encrypted DB backup ran and a **test restore** succeeded (section 7)
- [ ] Photo replication to the second location ran
- [ ] The erasure-request log exists (for re-applying erasures after a restore)

**Operations**
- [ ] GlitchTip running on `errors.<domain>`; `SENTRY_DSN`/`WEB_SENTRY_DSN` use the internal host; alert emails arrive
- [ ] Uptime (GlitchTip + one external), new-issue, retention, backup and disk alerts configured and each triggered once (section 8)
- [ ] CI is green on the release commit and `main` is protected; the release was cut with `scripts/release.sh` and deployed with `scripts/deploy.sh` (release check passed)
- [ ] Capacity sized for the biggest expected event (searches per second × processes); `SEARCH_MAX_CONCURRENT` reviewed
- [ ] `scripts/security-scan.sh` passes on the release tag; the full test suite passes from a clean checkout
- [ ] A super admin exists; organizers briefed (Drive folder sharing, moderation, removal requests)
- [ ] Legal texts reviewed by counsel (LEGAL_REVIEW.md); `LEGAL_*` set in `.env.prod`; `/imprint`, `/terms`, `/organizer-terms` and `/privacy` show your details (no `[placeholder]` left)
- [ ] Log rotation keeps server logs ≤ 14 days and backups drop deleted photos within 30 days (both promised in the Privacy Notice and the DPA)
- [ ] iOS app only: `APPLE_TEAM_ID`/`IOS_BUNDLE_ID` set and the AASA file validates; APNs key in the secret store; `IOS_MIN_SUPPORTED_VERSION` matches the oldest build you support

**Launch-day notes**
- [ ] Users will be asked to **consent again once** (the consent text changed), and all sessions are logged out once by migration 0008
- [ ] Rollback plan agreed: `scripts/rollback.sh` (automatic on a failed deploy); the pre-deploy dump is in `.deploy/`

**No-go** if any of these is not ticked: DPIA/DPAs, EU storage, the production guard passing, a successful
test restore, TLS A grade, or DMARC-aligned email.
