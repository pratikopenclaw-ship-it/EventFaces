"""Injection (Phase B §6): CSV parser robustness (SEC-029), mail header injection,
secrets in access logs (SEC-030), and structural checks (Celery JSON-only, Drive IDs)."""

import logging

import pytest

from app.core.email import Mail, build_message
from app.core.logging import RedactTokens
from app.services.drive_ids import parse_drive_folder_id
from app.workers.celery_app import celery_app
from tests.test_invites import invite_event  # noqa: F401  (fixture re-export)


@pytest.mark.parametrize(
    "payload",
    ["a" * 200_000, '"' + "x" * 200_000, "a@example.com\n" + "b" * 150_000],
    ids=["huge-cell", "unterminated-quote", "valid-then-huge"],
)
def test_malformed_invite_csv_is_a_clean_422(invite_event, payload: str) -> None:  # noqa: F811
    event, org = invite_event
    r = org.post(f"/api/events/{event.id}/invites", json={"csv": payload})
    assert r.status_code == 422, (r.status_code, r.text[:200])


def test_formula_and_markup_cells_are_not_invited(invite_event, mailer) -> None:  # noqa: F811
    event, org = invite_event
    r = org.post(
        f"/api/events/{event.id}/invites",
        json={"csv": '=HYPERLINK("http://x")@evil.com,<script>@x.com,ok@example.com'},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sent"] == ["ok@example.com"]


def test_mail_subject_cannot_inject_headers() -> None:
    msg = build_message(Mail(to="a@example.com", subject="Party\r\nBcc: victim@example.com\nX-Evil: 1", body="hi"))
    raw = msg.as_string()
    assert "\nBcc:" not in raw and "\nX-Evil:" not in raw
    assert msg["Subject"] == "Party Bcc: victim@example.com X-Evil: 1"


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        ('1.2.3.4 - "GET /api/downloads/eyJhbGciOi.payload.sig HTTP/1.1" 200', "eyJhbGciOi.payload.sig"),
        ('1.2.3.4 - "GET /api/invites/AbC_def-123456789012 HTTP/1.1" 200', "AbC_def-123456789012"),
        ('1.2.3.4 - "POST /api/removal-requests/tok_en-123456789/submit HTTP/1.1" 200', "tok_en-123456789"),
        ('1.2.3.4 - "GET /api/removal-requests/tok_en-123456789 HTTP/1.1" 200', "tok_en-123456789"),
        ('1.2.3.4 - "GET /reset-password?token=Zm9vYmFyYmF6 HTTP/1.1" 200', "Zm9vYmFyYmF6"),
        ('1.2.3.4 - "GET /invite/AbC_def-123456789012 HTTP/1.1" 200', "AbC_def-123456789012"),
    ],
)
def test_access_log_redacts_bearer_tokens_in_urls(line: str, secret: str) -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s", (line,), None)
    assert RedactTokens().filter(record)
    assert secret not in record.getMessage()
    assert "[redacted]" in record.getMessage()


def test_uvicorn_access_args_are_redacted_too() -> None:
    """uvicorn passes (client, method, path, http_version, status) as args."""
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/invites/AbC_def-123456789012", "1.1", 200), None,
    )
    RedactTokens().filter(record)
    assert "AbC_def-123456789012" not in record.getMessage()
    assert "/api/invites/[redacted]" in record.getMessage()


def test_redaction_filter_is_installed_on_uvicorn_access() -> None:
    import app.main  # noqa: F401  (installs logging config)

    assert any(isinstance(f, RedactTokens) for f in logging.getLogger("uvicorn.access").filters)


def test_non_secret_paths_are_untouched() -> None:
    line = '"GET /api/events/4b1d/photos?page=2 HTTP/1.1" 200'
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "%s", (line,), None)
    RedactTokens().filter(record)
    assert record.getMessage() == line


def test_celery_accepts_json_only() -> None:
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"


@pytest.mark.parametrize(
    "value",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://evil.example/drive.google.com/folders/AAAAAAAAAAAA/../x",
        "file:///etc/passwd",
        "gopher://drive.google.com/folders/..%2f..%2f",
        "1abc/../../x",
        "abc def ghi jk",
        "https://drive.google.com/drive/folders/abc%2F..%2Fdef1234",
    ],
)
def test_drive_input_can_only_yield_a_plain_id(value: str) -> None:
    folder_id = parse_drive_folder_id(value)
    assert folder_id is None or folder_id.replace("-", "").replace("_", "").isalnum()
