"""The real GoogleDriveClient against mocked HTTP: pagination, retries, access errors."""

import json

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from app.services.drive import DriveAccessError, DriveFileTooLarge, GoogleDriveClient

FOLDER = "1AbCdEfGhIjKlMnOpQr"


def _client(responses: list[tuple[dict, str | bytes]], monkeypatch) -> GoogleDriveClient:
    monkeypatch.setattr("googleapiclient.http.time.sleep", lambda _s: None)  # no real backoff waits
    http = HttpMockSequence(responses)
    return GoogleDriveClient(build("drive", "v3", http=http, static_discovery=True))


def _page(ids: list[str], token: str | None = None) -> tuple[dict, str]:
    body: dict = {"files": [{"id": i, "name": f"{i}.jpg", "mimeType": "image/jpeg", "size": "10"} for i in ids]}
    if token:
        body["nextPageToken"] = token
    return {"status": "200"}, json.dumps(body)


def _error(status: int, reason: str) -> tuple[dict, str]:
    body = {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}
    return {"status": str(status)}, json.dumps(body)


def test_paginates_and_retries_rate_limits(monkeypatch) -> None:
    client = _client(
        [
            _page(["a", "b"], token="p2"),
            _error(429, "rateLimitExceeded"),
            _error(403, "userRateLimitExceeded"),
            _error(503, "backendError"),
            _page(["c"]),
        ],
        monkeypatch,
    )
    pages = list(client.list_images(FOLDER))
    assert [[f.id for f in p] for p in pages] == [["a", "b"], ["c"]]


def test_folder_not_shared_raises_access_error(monkeypatch) -> None:
    client = _client([_error(404, "notFound")], monkeypatch)
    with pytest.raises(DriveAccessError, match="isn't shared with"):
        list(client.list_images(FOLDER))


def test_permission_denied_raises_access_error(monkeypatch) -> None:
    client = _client([_error(403, "insufficientFilePermissions")], monkeypatch)
    with pytest.raises(DriveAccessError):
        list(client.list_images(FOLDER))


def test_download_enforces_size_limit(monkeypatch) -> None:
    payload = b"\xff\xd8\xff" + b"0" * 2000
    headers = {"status": "200", "content-range": f"bytes 0-{len(payload) - 1}/{len(payload)}"}
    client = _client([(headers, payload)], monkeypatch)
    with pytest.raises(DriveFileTooLarge):
        client.download("file1", max_bytes=1000)


def test_download_returns_bytes(monkeypatch) -> None:
    payload = b"\xff\xd8\xff" + b"0" * 100
    headers = {"status": "200", "content-range": f"bytes 0-{len(payload) - 1}/{len(payload)}"}
    client = _client([(headers, payload)], monkeypatch)
    assert client.download("file1", max_bytes=10_000) == payload
