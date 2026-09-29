from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    verify_token_hours: int = 48
    reset_token_minutes: int = 60

    database_url: str
    test_database_url: str | None = None
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

    selfie_max_bytes: int = 10 * 1024 * 1024
    search_max_results: int = 500
    search_grant_days: int = 7
    search_rate_limit: str = "10/600"
    download_token_seconds: int = 120
    zip_max_photos: int = 500

    guest_upload_max_bytes: int = 25 * 1024 * 1024
    guest_upload_rate_limit: str = "60/3600"
    upload_url_seconds: int = 600
    invite_days: int = 14

    audit_retention_days: int = 365
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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
