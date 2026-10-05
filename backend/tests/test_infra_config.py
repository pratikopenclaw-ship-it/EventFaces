"""Infra (Phase B §7): production refuses insecure configuration (SEC-033), docs are off
in production, CORS is an allowlist, the bucket is private, secrets aren't in the repo."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import storage
from app.core.config import Settings, get_settings

STRONG = "x7Rq9mZ2vL4pW8kT3nB6yH1cF5dJ0sGa"
PROD_OK = {
    "environment": "production",
    "frontend_url": "https://photos.example.org",
    "cookie_secure": True,
    "jwt_secret": STRONG + "jwt",
    "download_token_secret": STRONG + "dl",
    "database_url": "postgresql+psycopg://eventfaces_app:Zk3p9QwLr8TmV2xY@db:5432/eventfaces",
    "redis_url": "redis://:Q8wLz3Rk9TmP2vXy@redis:6379/0",
    "s3_access_key": "AKIAEXAMPLEKEY123",
    "s3_secret_key": "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY",
    "smtp_host": "smtp.example.org",
    "legal_operator_name": "Example Photos GmbH",
    "legal_operator_address": "Musterstraße 1\\n10115 Berlin",
    "legal_representative": "Erika Mustermann",
    "legal_email": "legal@example.org",
    "legal_phone": "+49 30 1234567",
    "legal_dpo_contact": "dpo@example.org",
    "legal_supervisory_authority": "Berliner Beauftragte für Datenschutz und Informationsfreiheit",
    "legal_email_provider": "Example Mail GmbH, Germany",
    "sentry_dsn": "http://0123abcd@glitchtip:8000/1",
    "glitchtip_secret_key": STRONG + "gt",
    "glitchtip_db_password": STRONG + "gtdb",
    "allow_test_payments": True,  # UAT: the fake provider is the only one so far
    "payments_webhook_secret": STRONG + "pay",
}


def test_valid_production_settings_load() -> None:
    Settings(**PROD_OK)


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"jwt_secret": "change-me-dev-only-secret-change-me-dev-only"}, "JWT_SECRET"),
        ({"download_token_secret": "change-me-download-secret-change-me-download"}, "DOWNLOAD_TOKEN_SECRET"),
        ({"download_token_secret": STRONG + "jwt"}, "DOWNLOAD_TOKEN_SECRET"),  # same as JWT secret
        ({"jwt_secret": "a" * 40}, "JWT_SECRET"),  # low entropy
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"frontend_url": "http://photos.example.org"}, "FRONTEND_URL"),
        ({"database_url": "postgresql+psycopg://eventfaces_app:eventfaces_app_dev@db:5432/eventfaces"}, "DATABASE_URL"),
        ({"database_url": "postgresql+psycopg://eventfaces:secret-owner-pass@db:5432/eventfaces"}, "DATABASE_URL"),
        ({"redis_url": "redis://redis:6379/0"}, "REDIS_URL"),
        ({"redis_url": "redis://:eventfaces_redis_dev@redis:6379/0"}, "REDIS_URL"),
        ({"s3_secret_key": "eventfaces-dev-secret"}, "S3_SECRET_KEY"),
        ({"smtp_host": "mailpit"}, "SMTP_HOST"),
        ({"allow_selfie_file_upload": True, "trusted_proxy_hops": 0}, None),  # allowed: not a secret
        ({"app_attest_app_id": "ABCDE12345.app.eventfaces.ios"}, "APP_ATTEST_ENV"),  # development keys
        ({"legal_operator_name": ""}, "LEGAL_OPERATOR_NAME"),  # Impressum/Terms can't ship with placeholders
        ({"legal_phone": "  "}, "LEGAL_PHONE"),
        ({"legal_dpo_contact": ""}, "LEGAL_DPO_CONTACT"),
        ({"legal_register": "", "legal_vat_id": ""}, None),  # optional (sole proprietors)
        ({"app_attest_app_id": "ABCDE12345.app.eventfaces.ios", "app_attest_env": "production"}, None),
        ({"sentry_dsn": ""}, "SENTRY_DSN"),  # UAT/production must report errors
        ({"sentry_dsn": "http://0123abcd@errors.example.org/1"}, "SENTRY_DSN"),  # key in plaintext over the internet
        ({"sentry_dsn": "https://errors.example.org/1"}, "SENTRY_DSN"),  # no key
        ({"sentry_dsn": "https://0123abcd@errors.example.org/"}, "SENTRY_DSN"),  # no project
        ({"sentry_dsn": "https://0123abcd@errors.example.org/3"}, None),
        ({"glitchtip_secret_key": "change-me-glitchtip-secret-change-me"}, "GLITCHTIP_SECRET_KEY"),
        ({"glitchtip_secret_key": ""}, "GLITCHTIP_SECRET_KEY"),
        ({"glitchtip_db_password": "glitchtip_dev_password"}, "GLITCHTIP_DB_PASSWORD"),
        ({"glitchtip_db_password": "short"}, "GLITCHTIP_DB_PASSWORD"),
        ({"allow_test_payments": False}, "ALLOW_TEST_PAYMENTS"),  # no fake payments in production by accident
        ({"payments_webhook_secret": "change-me-payments-webhook-secret-dev-only"}, "PAYMENTS_WEBHOOK_SECRET"),
        ({"payments_webhook_secret": "b" * 40}, "PAYMENTS_WEBHOOK_SECRET"),
    ],
)
def test_production_refuses_insecure_settings(override: dict[str, object], problem: str | None) -> None:
    if problem is None:
        Settings(**{**PROD_OK, **override})
        return
    with pytest.raises(ValidationError, match=problem):
        Settings(**{**PROD_OK, **override})


def test_dev_defaults_still_load_outside_production() -> None:
    Settings(**{**PROD_OK, "environment": "development", "cookie_secure": False, "smtp_host": "mailpit"})


def test_docs_and_openapi_are_off_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "environment", "production")
    client = TestClient(create_app())
    for path in ("/api/docs", "/api/openapi.json", "/api/redoc", "/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_api_sends_no_cors_grants_to_foreign_origins(client: TestClient) -> None:
    r = client.options(
        "/api/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-csrf-token"},
    )
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-credentials" not in r.headers


def test_bucket_cors_is_an_allowlist_for_put_only() -> None:
    storage.configure_cors([get_settings().frontend_url])  # what `cli init-storage` does
    rules = storage.get_s3().get_bucket_cors(Bucket=get_settings().s3_bucket)["CORSRules"]
    for rule in rules:
        assert "*" not in rule["AllowedOrigins"]
        assert set(rule["AllowedMethods"]) == {"PUT"}
    base = (get_settings().s3_endpoint_url or "").rstrip("/")
    preflight = {"Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"}
    url = f"{base}/{get_settings().s3_bucket}/events/x/uploads/y"
    evil = httpx.options(url, headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in evil.headers
    ours = httpx.options(url, headers={"Origin": get_settings().frontend_url, **preflight})
    assert ours.headers.get("access-control-allow-origin") == get_settings().frontend_url


def test_bucket_objects_are_not_publicly_readable() -> None:
    key = "events/public-read-probe/photos/x/original.jpg"
    storage.put_jpeg(key, b"\xff\xd8\xff probe")
    try:
        base = (get_settings().s3_endpoint_url or "").rstrip("/")
        bucket = get_settings().s3_bucket
        assert httpx.get(f"{base}/{bucket}/{key}").status_code in (401, 403)
        assert httpx.get(f"{base}/{bucket}?list-type=2").status_code in (401, 403)
        assert httpx.put(f"{base}/{bucket}/anon-write", content=b"x").status_code in (401, 403)
    finally:
        storage.delete_keys(key)
