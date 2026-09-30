# Deploying EventFaces (EU)

Target: **one Hetzner Cloud server in Germany** running `docker-compose.prod.yml` (Caddy for TLS,
Next.js, FastAPI, Celery worker and beat, Postgres + pgvector, Redis), with photos in **Cloudflare R2
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
4. Calibrate the face-match thresholds on **consented** pilot data (see step 10). The shipped
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
2. Add a **CAA** record so only Let's Encrypt can issue for the domain:
   `photos.example.org. CAA 0 issue "letsencrypt.org"`.
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
   for n in JWT_SECRET DOWNLOAD_TOKEN_SECRET POSTGRES_PASSWORD APP_DB_PASSWORD REDIS_PASSWORD; do
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
   - Remove every `TEST_*` variable.
4. The API **refuses to start** in production if a value is still a development or public default
   (dev or low-entropy secrets, equal JWT and download secrets, insecure cookies, a non-https frontend,
   the owner role or a dev password in `DATABASE_URL`, Redis without a private password, the dev S3
   key, or Mailpit as SMTP). The error lists every problem.
5. **Rotation** (at least yearly, and immediately after a suspected leak or a staff change):

   | Secret | How | Effect |
   |---|---|---|
   | `JWT_SECRET` | New value, restart `api` | Everyone is logged out |
   | `DOWNLOAD_TOKEN_SECRET` | New value, restart `api` | Download links (2-minute life) stop working |
   | `APP_DB_PASSWORD` | `ALTER ROLE eventfaces_app PASSWORD '…'` as the owner, update `.env.prod`, restart `api`, `worker`, `beat` | None |
   | `POSTGRES_PASSWORD` | `ALTER ROLE eventfaces PASSWORD '…'`, update `.env.prod` | Used only by migrations |
   | `REDIS_PASSWORD` | Update `.env.prod`, restart `redis`, `api`, `worker`, `beat` | Rate-limit counters and queued-search statuses reset |
   | R2 / SMTP / Google keys | Create a new key at the provider, update `.env.prod`, restart, then revoke the old key | None |

## 6. Deploy

**(server)**, from the repository directory:
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod ps          # all services healthy
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python -m app.cli create-superadmin --email you@example.org
```
The API runs database migrations and storage checks on start. Then smoke test: log in, create an
event, upload a photo as a guest, search with your own face, download it, and delete the test event.

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

- **Uptime:** an external check (EU-hosted, e.g. a self-hosted Uptime Kuma on another host) on
  `https://photos.example.org/api/health` every minute, alerting after 2 failures.
  Also alert on TLS certificate expiry below 14 days.
- **Container health:** `docker compose … ps` shows healthchecks. Alert if any service restarts
  repeatedly (for example a cron job running `docker compose ps --format json`, or node-exporter
  plus cAdvisor with Prometheus and Grafana).
- **Application signals** to alert on (from the API logs, `docker compose … logs api`):
  - 5xx rate > 1% over 5 minutes.
  - **503 rate** (search busy, queue full, hashing busy or pool busy). This is the capacity signal:
    sustained 503s mean it's time to add processes or a bigger server.
  - `Refusing to start in production` (a configuration error on deploy).
  - A missing hourly `Retention run` log line from `beat`/`worker` (retention is a GDPR duty).
  - Celery backlog: `docker compose … exec redis redis-cli -a "$REDIS_PASSWORD" LLEN celery` and
    `LLEN index` > 500 for 30 minutes.
- **Host:** disk > 80%, memory > 90%, load. Hetzner Cloud's monitoring graphs cover the basics.
- **Backups:** alert if the nightly backup hasn't run in 36 hours (`restic snapshots --latest 1`).
- **Logs:** Docker keeps 5 × 50 MB per container (step 1). If you ship logs elsewhere, keep them
  for 30–90 days: they contain IP addresses and user IDs (never selfies or embeddings). Keep Caddy
  access logging off, or apply the same token redaction as `app/core/logging.RedactTokens`.

## 9. Updating and rolling back

1. Take a fresh database backup (run the cron script by hand).
2. `git fetch --tags && git checkout <new-tag>`, then
   `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`. Migrations run
   automatically.
3. Watch the logs and `/api/health`, then smoke test (step 6).
4. **Rollback:** `git checkout <previous-tag>` and redeploy. If the new release added a migration,
   first run `docker compose … exec api alembic downgrade <previous-revision>` (downgrades are tested
   on populated data), or restore the backup from step 1.
5. Run `scripts/security-scan.sh` in CI on every release, and rebuild images at least monthly to
   pick up base-image security fixes.

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
- [ ] Uptime, 5xx, 503, retention-job, backup and disk alerts are configured and were tested once (trigger each alert deliberately)
- [ ] Capacity sized for the biggest expected event (searches per second × processes); `SEARCH_MAX_CONCURRENT` reviewed
- [ ] `scripts/security-scan.sh` passes on the release tag; the full test suite passes from a clean checkout
- [ ] A super admin exists; organizers briefed (Drive folder sharing, moderation, removal requests)

**Launch-day notes**
- [ ] Users will be asked to **consent again once** (the consent text changed), and all sessions are logged out once by migration 0008
- [ ] Rollback plan agreed: previous tag + backup from right before the deploy

**No-go** if any of these is not ticked: DPIA/DPAs, EU storage, the production guard passing, a successful
test restore, TLS A grade, or DMARC-aligned email.
