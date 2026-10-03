"""Reading selfies from a request: memory only, never disk.

Two body formats:
- a single image (Content-Type image/jpeg|png|heic|heif)
- a selfie set (Content-Type application/x-selfie-set): the images concatenated, with
  headers `X-Selfie-Shots: front,left,right` and `X-Selfie-Lengths: n1,n2,n3`.

We deliberately don't use multipart/UploadFile: Starlette spools uploads over 1 MB to
a temporary file on disk, and a selfie must never be written anywhere.
"""

import re

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

SELFIE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif"}
SELFIE_SET_TYPE = "application/x-selfie-set"
MAX_SHOTS = 3
_SHOT = re.compile(r"^(front|left|right|any)$")


def _content_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


def selfie_content_type(request: Request) -> str | None:
    """The request's single-image content type, or None if the body isn't an image."""
    ct = _content_type(request)
    return ct if ct in SELFIE_TYPES else None


def is_selfie_set(request: Request) -> bool:
    return _content_type(request) == SELFIE_SET_TYPE


async def _read_body(request: Request, limit: int, too_large_message: str = "Selfie is too large (max 10 MB per photo)") -> bytes:
    declared = request.headers.get("content-length")
    too_large = HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, too_large_message)
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


async def read_capped_body(request: Request, limit: int, too_large_message: str) -> bytes:
    """A raw request body read in memory with a hard cap (never spooled to disk)."""
    return await _read_body(request, limit, too_large_message)


async def read_selfie(request: Request) -> bytes:
    """A single raw image body, capped at SELFIE_MAX_BYTES."""
    return await _read_body(request, get_settings().selfie_max_bytes)


async def read_selfie_set(request: Request) -> list[tuple[str, bytes]]:
    """Split a selfie-set body into (shot, bytes) using the length header."""
    per_shot = get_settings().selfie_max_bytes
    bad = HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed selfie set")
    shots = [s.strip() for s in request.headers.get("x-selfie-shots", "").split(",") if s.strip()]
    try:
        lengths = [int(n) for n in request.headers.get("x-selfie-lengths", "").split(",")]
    except ValueError as e:
        raise bad from e
    if not 1 <= len(shots) <= MAX_SHOTS or len(shots) != len(lengths) or not all(_SHOT.match(s) for s in shots):
        raise bad
    if any(n <= 0 or n > per_shot for n in lengths):
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Selfie is too large (max 10 MB per photo)")
    body = await _read_body(request, sum(lengths))
    if len(body) != sum(lengths):
        raise bad
    parts, offset = [], 0
    for shot, n in zip(shots, lengths, strict=True):
        parts.append((shot, body[offset : offset + n]))
        offset += n
    return parts


def _binary(*types: str) -> dict[str, dict[str, object]]:
    return {t: {"schema": {"type": "string", "format": "binary"}} for t in types}


def _header(name: str, description: str, required: bool = False) -> dict[str, object]:
    return {"name": name, "in": "header", "required": required, "description": description, "schema": {"type": "string"}}


# OpenAPI for the raw-body endpoints (they read the request stream, so FastAPI can't infer
# it). The iOS client is generated from this.
SEARCH_OPENAPI: dict[str, object] = {
    "requestBody": {
        "required": True,
        "description": "Camera: a selfie set (front, left, right JPEGs concatenated). Upload: one image.",
        "content": _binary(SELFIE_SET_TYPE, "image/jpeg", "image/png", "image/heic"),
    },
    "parameters": [
        _header("X-Capture-Token", "Single-use capture token (camera searches)"),
        _header("X-Selfie-Shots", "Comma-separated shot names, e.g. front,left,right"),
        _header("X-Selfie-Lengths", "Comma-separated byte lengths of the shots"),
    ],
}
REMOVAL_SUBMIT_OPENAPI: dict[str, object] = {
    "requestBody": {"required": False, "description": "Optional reference selfie", "content": _binary("image/jpeg", "image/png", "image/heic")},
}
