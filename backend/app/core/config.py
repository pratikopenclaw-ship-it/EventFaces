from functools import lru_cache
from typing import Literal

import math
from collections import Counter
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    frontend_url: str = "http://localhost:3000"
    cookie_secure: bool = False

    jwt_secret: str = Field(min_length=32)
    download_token_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    db_statement_timeout_ms: int = Field(default=60_000, ge=1000)
    # Pooled connections per process (SEC-042). Keep processes × (size + overflow) well
    # under Postgres max_connections (100 by default).
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    # Argon2 hashes in flight per process (~64 MiB each); excess waits this long, then 503.
    password_hash_max_concurrent: int = Field(default=4, ge=1, le=64)
    password_hash_wait_seconds: float = Field(default=3.0, ge=0, le=30)
    # A rotated refresh token presented again within this window is a benign cross-tab
    # race; later than that it is treated as theft and the whole session is revoked.
    refresh_reuse_grace_seconds: int = Field(default=20, ge=0, le=120)
    verify_token_hours: int = 48
    reset_token_minutes: int = 60

    database_url: str  # runtime: least-privilege role (eventfaces_app)
    migration_database_url: str | None = None  # schema owner, used only by Alembic
    test_database_url: str | None = None
    test_migration_database_url: str | None = None
    redis_url: str = "redis://redis:6379/0"
    test_redis_url: str | None = None

    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "eventfaces"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = False
    email_from: str = "EventFaces <no-reply@eventfaces.local>"

    google_service_account_json: str = ""
    google_service_account_file: str = ""

    face_match_threshold: float = 0.45  # "possible match" cutoff (lower tier)
    match_best_threshold: float = 0.55  # "best match" cutoff (upper tier)

    # Selfie capture & quality gates
    allow_selfie_file_upload: bool = False  # global switch; the event must ALSO allow it
    capture_token_seconds: int = 60
    selfie_min_width: int = 640
    selfie_min_height: int = 480
    selfie_min_det_score: float = 0.8
    selfie_face_height_min: float = 0.30  # face height / frame height
    selfie_face_height_max: float = 0.60
    selfie_max_yaw: float = 20.0
    selfie_max_pitch: float = 15.0
    selfie_max_roll: float = 15.0
    selfie_front_max_yaw: float = 12.0  # the "front" shot must face the camera
    selfie_side_min_yaw: float = 5.0  # "slight left/right" shots must turn at least this much
    selfie_min_blur: float = 30.0  # Laplacian variance of the face normalized to 160 px height
    selfie_min_brightness: float = 60.0  # mean face luma, 0-255
    selfie_max_brightness: float = 210.0
    selfie_same_person_min: float = 0.5  # the 3 shots must show the same person
    face_min_det_score: float = 0.5
    face_det_size: int = 640
    face_model_root: str = "/models"
    # Which face-recognition engine to use: "insightface" or "package.module:Class"
    # implementing services/face_engine.FaceEngine. Switching needs a reindex
    # (`python -m app.cli reindex-faces`) and threshold recalibration.
    face_engine: str = "insightface"

    selfie_max_bytes: int = 10 * 1024 * 1024
    # Pixel limits, checked from the image header before decoding (decoded RGB = 3 B/px).
    selfie_max_pixels: int = Field(default=50_000_000, ge=1_000_000)
    image_max_pixels: int = Field(default=120_000_000, ge=1_000_000)
    search_max_results: int = 500
    search_grant_days: int = 7
    search_rate_limit: str = "10/600"
    # Ceiling across all accounts in one event, so many accounts can't multiply the
    # per-user limit to scrape it. Default sits above what one worker can process.
    search_event_rate_limit: str = "600/600"
    # Face work in flight or waiting per API process (SEC-039). Beyond it, a request waits
    # up to search_queue_wait_seconds for a slot, then gets 503 + Retry-After. The face
    # model is serialized per process (~0.9 searches/s on the load-test machine), so size
    # this as throughput × acceptable wait, not by CPU count: 6 ≈ 7 s worst admitted wait.
    search_max_concurrent: int = Field(default=6, ge=1, le=64)
    search_queue_wait_seconds: float = Field(default=5.0, ge=0, le=30)
    # Overflow: searches that can't get a slot are queued in process memory and the user
    # is notified when done (services/search_queue.py). Bounded by jobs and bytes; 0 jobs
    # disables it (busy searches then get 503). Queued jobs older than the TTL are
    # reported as expired (e.g. lost in a restart).
    search_overflow_queue_size: int = Field(default=20, ge=0, le=500)
    search_queue_max_bytes: int = Field(default=64 * 1024 * 1024, ge=0)
    search_queue_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    download_token_seconds: int = 120
    zip_max_photos: int = 500

    guest_upload_max_bytes: int = 25 * 1024 * 1024
    guest_upload_rate_limit: str = "60/3600"
    # Storage-exhaustion caps on live guest uploads (rejected/removed ones don't count).
    guest_upload_max_per_user: int = Field(default=200, ge=1)
    guest_upload_max_per_event: int = Field(default=5000, ge=1)
    upload_url_seconds: int = 600
    invite_days: int = 14

    audit_retention_days: int = Field(default=365, ge=30)  # search_audit trigger blocks younger deletes
    removal_request_retention_days: int = 180
    unverified_user_days: int = 14
    removal_token_hours: int = 48

    max_import_bytes: int = 50 * 1024 * 1024
    drive_sync_stale_minutes: int = 60

    # Number of trusted reverse proxies that append to X-Forwarded-For (0 = ignore it).
    trusted_proxy_hops: int = 0
    login_rate_limit: str = "10/300"
    join_rate_limit: str = "20/300"
    join_lockout_attempts: int = 5
    join_lockout_seconds: int = 900

    # Mobile app (bearer auth, passwordless sign-in). Access tokens use access_token_minutes;
    # refresh tokens refresh_token_days and must be signed by the device key (device-bound).
    mobile_code_ttl_minutes: int = Field(default=10, ge=1, le=60)
    mobile_code_max_attempts: int = Field(default=5, ge=1, le=10)  # per code, then it dies
    mobile_code_request_rate_limit: str = "5/900"  # per email (and x5 per IP)
    mobile_code_verify_rate_limit: str = "20/900"  # per IP
    mobile_signature_skew_seconds: int = Field(default=60, ge=10, le=300)
    # Bearer requests below the minimum get 426 (force an update after a security fix).
    ios_min_supported_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    ios_latest_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    ios_update_url: str = "https://apps.apple.com/"

    # APNs (token-based auth). Push is disabled until all four are set.
    apns_key_p8: str = ""  # contents of the .p8 key (PEM)
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_topic: str = ""  # the app's bundle id
    apns_env: Literal["sandbox", "production"] = "sandbox"
    apns_timeout_seconds: float = Field(default=10.0, ge=1, le=60)

    # App Attest. Report-only: results are recorded and logged, never block a request.
    # Off until APP_ATTEST_APP_ID ("<Team ID>.<bundle id>") is set.
    app_attest_app_id: str = Field(default="", pattern=r"^([A-Z0-9]{10}\.[A-Za-z0-9.-]+)?$")
    app_attest_env: Literal["development", "production"] = "development"

    # Error reporting (self-hosted GlitchTip, Sentry protocol): off unless SENTRY_DSN is
    # set. core/monitoring.py scrubs every event (no bodies, cookies, tokens, emails).
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = Field(default=0.05, ge=0, le=1)
    # The deployed build (git sha / tag), set at image build time; shown by /api/health.
    app_version: str = Field(default="dev", pattern=r"^[A-Za-z0-9._+-]{1,40}$")
    # Payments (services/billing). "fake" is a test provider: a TEST MODE checkout page in
    # this app, test cards only, no real money. Production refuses it unless
    # ALLOW_TEST_PAYMENTS=true (UAT). The webhook secret signs provider confirmations.
    payments_provider: Literal["fake"] = "fake"
    allow_test_payments: bool = False
    payments_webhook_secret: str = Field(min_length=32)
    checkout_rate_limit: str = "10/3600"  # checkouts started per user
    payment_attempt_rate_limit: str = "20/3600"  # test-card attempts per user
    webhook_rate_limit: str = "120/60"  # confirmations per IP

    # GlitchTip heartbeat monitor pinged after every successful hourly retention run, so a
    # stalled retention job (a GDPR duty) raises an alert. Empty = off.
    retention_heartbeat_url: str = Field(default="", pattern=r"^(https?://\S+)?$")
    # GlitchTip's own secrets (read by the glitchtip container from .env.prod); checked here
    # so every production secret is in one guard.
    glitchtip_secret_key: str = ""
    glitchtip_db_password: str = ""

    # Operator identity for the legal documents (services/legal.py: Impressum, Terms,
    # Privacy Notice). Empty fields show as visible placeholders; production refuses to
    # start while a required one is empty. LEGAL_OPERATOR_ADDRESS may use "\n" for lines.
    legal_operator_name: str = ""
    legal_operator_address: str = ""
    legal_representative: str = ""  # managing director / owner, also responsible under § 18(2) MStV
    legal_email: str = ""
    legal_phone: str = ""
    legal_register: str = ""  # e.g. "Amtsgericht Berlin-Charlottenburg, HRB 123456" (optional)
    legal_vat_id: str = ""  # optional
    legal_dpo_contact: str = ""
    legal_supervisory_authority: str = ""
    legal_hosting_provider: str = "Hetzner Online GmbH, Gunzenhausen (Germany)"
    legal_storage_provider: str = "Cloudflare, Inc. (R2 object storage, EU jurisdiction)"
    legal_email_provider: str = ""


    @model_validator(mode="after")
    def _refuse_insecure_production(self) -> "Settings":
        """Fail closed: production must not start with development defaults or values
        that are public in this repository (.env.example, docker-compose.yml)."""
        if self.environment != "production":
            return self
        problems: list[str] = []
        for name in ("jwt_secret", "download_token_secret"):
            value = getattr(self, name)
            if value.startswith("change-me") or _entropy_bits(value) < 100:
                problems.append(f"{name.upper()} must be a random secret (e.g. `openssl rand -base64 48`)")
        if self.jwt_secret == self.download_token_secret:
            problems.append("DOWNLOAD_TOKEN_SECRET must differ from JWT_SECRET")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if urlsplit(self.frontend_url).scheme != "https":
            problems.append("FRONTEND_URL must be https")
        db = urlsplit(self.database_url)
        if db.username != "eventfaces_app" or not db.password or db.password in _PUBLIC_PASSWORDS:
            problems.append("DATABASE_URL must use the least-privilege eventfaces_app role with a private password")
        redis_password = urlsplit(self.redis_url).password
        if not redis_password or redis_password in _PUBLIC_PASSWORDS:
            problems.append("REDIS_URL must include a private password")
        if not self.s3_secret_key or self.s3_secret_key in _PUBLIC_PASSWORDS:
            problems.append("S3_SECRET_KEY must be set to a private key")
        if self.smtp_host == "mailpit":
            problems.append("SMTP_HOST must point at a real mail server")
        if self.apns_key_p8 and "BEGIN PRIVATE KEY" not in self.apns_key_p8:
            problems.append("APNS_KEY_P8 must be the PEM contents of the .p8 key")
        if self.apns_key_p8 and self.apns_env != "production":
            problems.append("APNS_ENV must be production")
        legal_required = {
            "LEGAL_OPERATOR_NAME": self.legal_operator_name,
            "LEGAL_OPERATOR_ADDRESS": self.legal_operator_address,
            "LEGAL_REPRESENTATIVE": self.legal_representative,
            "LEGAL_EMAIL": self.legal_email,
            "LEGAL_PHONE": self.legal_phone,
            "LEGAL_DPO_CONTACT": self.legal_dpo_contact,
            "LEGAL_SUPERVISORY_AUTHORITY": self.legal_supervisory_authority,
            "LEGAL_EMAIL_PROVIDER": self.legal_email_provider,
        }
        missing = [k for k, v in legal_required.items() if not v.strip()]
        if missing:
            problems.append("legal identity incomplete (Impressum, Terms, Privacy Notice): set " + ", ".join(missing))
        if self.app_attest_app_id and self.app_attest_env != "production":
            problems.append("APP_ATTEST_ENV must be production")  # development keys are never accepted in production
        if self.payments_provider == "fake" and not self.allow_test_payments:
            problems.append("PAYMENTS_PROVIDER=fake takes no real payments: set ALLOW_TEST_PAYMENTS=true only for UAT")
        if self.payments_webhook_secret.startswith("change-me") or _entropy_bits(self.payments_webhook_secret) < 100:
            problems.append("PAYMENTS_WEBHOOK_SECRET must be a random secret")
        if not _valid_production_dsn(self.sentry_dsn):
            problems.append("SENTRY_DSN must be set: https://<key>@errors.<domain>/<project> or http://<key>@glitchtip:8000/<project>")
        if self.glitchtip_secret_key.startswith("change-me") or _entropy_bits(self.glitchtip_secret_key) < 100:
            problems.append("GLITCHTIP_SECRET_KEY must be a random secret")
        if len(self.glitchtip_db_password) < 16 or self.glitchtip_db_password in _PUBLIC_PASSWORDS:
            problems.append("GLITCHTIP_DB_PASSWORD must be a private password")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


# Development values published in .env.example / docker-compose.yml.
_PUBLIC_PASSWORDS = {"eventfaces", "eventfaces_app_dev", "eventfaces_redis_dev", "eventfaces-dev-secret", "eventfaces-dev", "glitchtip_dev_password"}


def _valid_production_dsn(dsn: str) -> bool:
    """A key, a numeric project, and https, or plain http only to the GlitchTip container
    on the internal compose network (the key never crosses the internet unencrypted)."""
    u = urlsplit(dsn)
    project = u.path.rstrip("/").rsplit("/", 1)[-1]
    if not u.username or not u.hostname or not project.isdigit():
        return False
    return u.scheme == "https" or (u.scheme == "http" and u.hostname == "glitchtip")


def _entropy_bits(value: str) -> float:
    """Shannon entropy of the string as a whole: catches 'aaaa…'-style secrets."""
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values()) * len(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
