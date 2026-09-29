"""Google Drive access via a service account (read-only).

Organizers share their folder with the service account's email. We list image files
in that folder (top level only), page through results, and download files by ID.
Transient failures (429, 5xx, 403 rate-limit reasons) are retried with exponential
backoff by googleapiclient's `num_retries`.
"""

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
IMAGE_MIME_TYPES = ("image/jpeg", "image/png", "image/heic", "image/heif")
NUM_RETRIES = 6
PAGE_SIZE = 1000


class DriveNotConfigured(RuntimeError):
    pass


class DriveAccessError(RuntimeError):
    """Folder missing or not shared with the service account (not retryable)."""


class DriveFileTooLarge(RuntimeError):
    pass


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None


class DriveClient(Protocol):
    def list_images(self, folder_id: str) -> Iterator[list[DriveFile]]: ...
    def download(self, file_id: str, max_bytes: int) -> bytes: ...


def _service_account_info() -> dict[str, Any] | None:
    s = get_settings()
    if s.google_service_account_json.strip():
        return json.loads(s.google_service_account_json)
    if s.google_service_account_file:
        return json.loads(Path(s.google_service_account_file).read_text())
    return None


def service_account_email() -> str | None:
    """The address organizers share folders with. Not secret."""
    try:
        info = _service_account_info()
    except (OSError, ValueError):
        return None
    return info.get("client_email") if info else None


def _query(folder_id: str) -> str:
    # folder_id is validated to [A-Za-z0-9_-] by parse_drive_folder_id, so no quoting issues.
    mimes = " or ".join(f"mimeType = '{m}'" for m in IMAGE_MIME_TYPES)
    return f"'{folder_id}' in parents and trashed = false and ({mimes})"


def _raise_access_error(e: HttpError, folder_id: str) -> None:
    if e.resp.status in (403, 404):
        email = service_account_email() or "the service account"
        raise DriveAccessError(
            f"Drive folder {folder_id} was not found or isn't shared with {email}"
        ) from e


class GoogleDriveClient:
    def __init__(self, service: Any) -> None:
        self._files = service.files()

    @classmethod
    def from_settings(cls) -> "GoogleDriveClient":
        from google.oauth2 import service_account

        info = _service_account_info()
        if not info:
            raise DriveNotConfigured("Google Drive service account is not configured")
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return cls(build("drive", "v3", credentials=creds, cache_discovery=False))

    def list_images(self, folder_id: str) -> Iterator[list[DriveFile]]:
        """Yield one list of image files per API page."""
        page_token: str | None = None
        while True:
            request = self._files.list(
                q=_query(folder_id),
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=PAGE_SIZE,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            try:
                response = request.execute(num_retries=NUM_RETRIES)
            except HttpError as e:
                _raise_access_error(e, folder_id)
                raise
            yield [
                DriveFile(
                    id=f["id"],
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    size=int(f["size"]) if f.get("size") else None,
                )
                for f in response.get("files", [])
            ]
            page_token = response.get("nextPageToken")
            if not page_token:
                return

    def download(self, file_id: str, max_bytes: int) -> bytes:
        request = self._files.get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=NUM_RETRIES)
            if buffer.tell() > max_bytes:
                raise DriveFileTooLarge(f"File exceeds {max_bytes // (1024 * 1024)} MB")
        return buffer.getvalue()


_override: DriveClient | None = None


@lru_cache
def _default_client() -> GoogleDriveClient:
    return GoogleDriveClient.from_settings()


def get_drive_client() -> DriveClient:
    return _override if _override is not None else _default_client()


def set_drive_client(client: DriveClient | None) -> None:
    """Used by tests to inject a fake Drive."""
    global _override
    _override = client
