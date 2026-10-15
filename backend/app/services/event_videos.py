"""Organizer-added video links. Only a fixed allowlist of providers may be stored (the
app renders these as iframes, and the CSP's frame-src is scoped to exactly these hosts
— frontend/src/lib/csp.ts — so an unlisted host must never reach the database or the
frontend has nothing safe to point an iframe at). parse_embed is pure and used both to
validate on save and to compute the embed_url returned to the frontend on read, so the
frontend never has to parse a video URL itself."""

import re
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import affected
from app.models import Event, EventVideo


@dataclass(frozen=True)
class Embed:
    provider: str
    embed_url: str


def _youtube(parsed) -> str | None:
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/embed/"):
            video_id = parsed.path.removeprefix("/embed/").split("/")[0]
        else:
            return None
    else:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id or ""):
        return None
    return f"https://www.youtube.com/embed/{video_id}"


def _vimeo(parsed) -> str | None:
    if parsed.netloc.lower().removeprefix("www.") != "vimeo.com":
        return None
    video_id = parsed.path.strip("/").split("/")[0]
    if not re.fullmatch(r"\d{6,12}", video_id):
        return None
    return f"https://player.vimeo.com/video/{video_id}"


def _instagram(parsed) -> str | None:
    if parsed.netloc.lower().removeprefix("www.") != "instagram.com":
        return None
    m = re.fullmatch(r"/(p|reel)/([A-Za-z0-9_-]{5,20})/?", parsed.path)
    if not m:
        return None
    return f"https://www.instagram.com/{m.group(1)}/{m.group(2)}/embed"


def _drive(parsed) -> str | None:
    if parsed.netloc.lower().removeprefix("www.") != "drive.google.com":
        return None
    m = re.fullmatch(r"/file/d/([A-Za-z0-9_-]{10,80})/.*", parsed.path)
    if not m:
        return None
    return f"https://drive.google.com/file/d/{m.group(1)}/preview"


def parse_embed(url: str) -> Embed:
    """Raises ValueError if the URL isn't a supported provider's video/file URL."""
    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise ValueError("Not a valid URL") from e
    if parsed.scheme != "https":
        raise ValueError("URL must use https")
    for provider, parser in (("youtube", _youtube), ("vimeo", _vimeo), ("instagram", _instagram), ("drive", _drive)):
        embed_url = parser(parsed)
        if embed_url is not None:
            return Embed(provider, embed_url)
    raise ValueError("Only YouTube, Vimeo, Instagram and Google Drive links are supported")


def add_video(db: Session, event: Event, title: str, url: str) -> EventVideo:
    try:
        parse_embed(url)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    video = EventVideo(id=uuid.uuid4(), event_id=event.id, title=title, url=url)
    db.add(video)
    db.commit()
    return video


def list_videos(db: Session, event: Event) -> list[EventVideo]:
    return list(db.scalars(select(EventVideo).where(EventVideo.event_id == event.id).order_by(EventVideo.created_at)))


def delete_video(db: Session, event: Event, video_id: uuid.UUID) -> None:
    result = db.execute(delete(EventVideo).where(EventVideo.id == video_id, EventVideo.event_id == event.id))
    if affected(result) == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    db.commit()
