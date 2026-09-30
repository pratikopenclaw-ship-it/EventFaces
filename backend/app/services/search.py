"""Selfie(s) → quality gate → embeddings → event-scoped vector search → grants + audit.

Privacy: selfie bytes, decoded images and query embeddings exist only in memory for
one request. What is stored: matched photo IDs (grants), an audit row with the match
count, and per-shot quality *metrics* (no image, no embedding, no user).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import (
    Event,
    Face,
    FeedbackVerdict,
    MatchFeedback,
    Photo,
    PhotoStatus,
    SearchAudit,
    SearchGrant,
    SelfieQuality,
    User,
)
from app.services import imaging, selfie_quality
from app.services.faces import current_model_id, detect_faces
from app.services.selfie_quality import ShotResult

# Bump when the consent text changes materially; users are asked again.
FACE_CONSENT_VERSION = "2026-09-30"  # + queued searches may wait in memory (search_queue.py)

Tier = Literal["best", "possible"]


class NoFaceFound(ValueError):
    pass


class SelfieRejected(ValueError):
    def __init__(self, code: str, message: str, shot: str) -> None:
        super().__init__(message)
        self.code, self.message, self.shot = code, message, shot


@dataclass(frozen=True)
class Match:
    photo_id: uuid.UUID
    similarity: float
    face_id: uuid.UUID | None = None

    @property
    def tier(self) -> Tier:
        return "best" if self.similarity >= get_settings().match_best_threshold else "possible"


def selfie_embedding(data: bytes) -> np.ndarray:
    """Embedding of the largest face (used for removal-request reference photos)."""
    img = imaging.load_image(data, max_pixels=get_settings().selfie_max_pixels)
    faces = detect_faces(img)
    del img
    if not faces:
        raise NoFaceFound("We couldn't find a face. Try again with your face centred and well lit.")
    largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return largest.embedding


def search_faces(
    db: Session,
    *,
    event_id: uuid.UUID,
    embedding: Sequence[float] | np.ndarray,
    threshold: float,
    limit: int,
) -> list[Match]:
    """Photos in ONE event containing a face with cosine similarity >= threshold.

    `event_id` is keyword-only and mandatory: there is deliberately no way to search
    across events. Only published photos are considered. Returns the best face per photo.
    """
    if event_id is None:  # defensive: never run an unscoped biometric search
        raise ValueError("event_id is required")

    # HNSW + a WHERE filter can return too few rows; iterative scans keep searching
    # the graph until `limit` filtered rows are found (pgvector >= 0.8).
    db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    db.execute(text("SET LOCAL hnsw.ef_search = 200"))

    distance = Face.embedding.cosine_distance(list(map(float, embedding))).label("distance")
    rows = db.execute(
        select(Face.photo_id, Face.id, distance)
        .join(Photo, Photo.id == Face.photo_id)
        .where(
            Face.event_id == event_id,
            Face.model == current_model_id(),  # never compare embeddings across models
            Photo.event_id == event_id,  # belt and braces: both sides must be this event
            Photo.status == PhotoStatus.published,
        )
        .order_by(distance)
        .limit(limit)
    ).all()

    best: dict[uuid.UUID, Match] = {}
    for photo_id, face_id, dist in rows:
        similarity = 1.0 - float(dist)
        if similarity >= threshold and similarity > (best[photo_id].similarity if photo_id in best else -1.0):
            best[photo_id] = Match(photo_id, similarity, face_id)
    return sorted(best.values(), key=lambda m: -m.similarity)


def merge_best(results: list[list[Match]]) -> list[Match]:
    """Several selfies searched separately → keep the best similarity per photo."""
    best: dict[uuid.UUID, Match] = {}
    for matches in results:
        for m in matches:
            if m.photo_id not in best or m.similarity > best[m.photo_id].similarity:
                best[m.photo_id] = m
    return sorted(best.values(), key=lambda m: -m.similarity)


def grant_expiry(event: Event, now: datetime) -> datetime:
    expiry = now + timedelta(days=get_settings().search_grant_days)
    if event.access_expires_at is not None:
        expiry = min(expiry, event.access_expires_at)
    return expiry


def _record_quality(db: Session, event: Event, results: list[ShotResult], search_id: int | None) -> None:
    db.add_all(
        SelfieQuality(
            event_id=event.id,
            search_id=search_id,
            shot=r.shot,
            passed=r.passed,
            reason=r.reason,
            score=r.score,
            **r.metrics_dict(),
        )
        for r in results
    )


@dataclass
class SearchOutcome:
    search_id: int
    matches: list[Match]
    quality: list[ShotResult]


def run_search(db: Session, user: User, event: Event, shots: list[tuple[str, bytes]]) -> SearchOutcome:
    """Validate every shot, then search with each passing one and merge.

    Raises SelfieRejected (with the first failing shot's reason) if any shot fails the
    quality gate or the shots don't show the same person. Metrics of every assessed
    shot are recorded either way, for the quality dashboard.
    """
    s = get_settings()
    results: list[ShotResult] = []
    for shot, data in shots:
        try:
            img = imaging.load_image(data, max_pixels=get_settings().selfie_max_pixels)
        except imaging.UnsupportedImage as e:
            raise SelfieRejected("unreadable", selfie_quality.MESSAGES["unreadable"], shot) from e
        results.append(selfie_quality.assess(img, shot))  # type: ignore[arg-type]
        del img

    failed = next((r for r in results if not r.passed), None)
    if failed is None and not selfie_quality.same_person(results):
        failed = ShotResult(results[-1].shot, False, "different_people")
    if failed is not None:
        _record_quality(db, event, results, None)
        db.commit()
        for r in results:
            r.embedding = None
        raise SelfieRejected(failed.reason or "rejected", failed.message or "", failed.shot)

    try:
        per_shot = [
            search_faces(db, event_id=event.id, embedding=r.embedding, threshold=s.face_match_threshold, limit=s.search_max_results)
            for r in results
            if r.embedding is not None
        ]
    finally:
        for r in results:
            r.embedding = None  # query embeddings are never stored or returned
    # Photos the user already said aren't them stay hidden in later searches.
    rejected = set(
        db.scalars(
            select(MatchFeedback.photo_id).where(
                MatchFeedback.user_id == user.id,
                MatchFeedback.event_id == event.id,
                MatchFeedback.verdict == FeedbackVerdict.not_me,
            )
        )
    )
    matches = [m for m in merge_best(per_shot) if m.photo_id not in rejected]

    # The audit row is written once, with its final values: search_audit is append-only.
    audit = SearchAudit(user_id=user.id, event_id=event.id, match_count=len(matches))
    db.add(audit)
    db.flush()

    if matches:
        now = utcnow()
        stmt = insert(SearchGrant).values(
            [
                {
                    "user_id": user.id,
                    "photo_id": m.photo_id,
                    "event_id": event.id,
                    "similarity": m.similarity,
                    "face_id": m.face_id,
                    "search_id": audit.id,
                    "expires_at": grant_expiry(event, now),
                }
                for m in matches
            ]
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "photo_id"],
                set_={
                    "similarity": stmt.excluded.similarity,
                    "face_id": stmt.excluded.face_id,
                    "search_id": stmt.excluded.search_id,
                    "expires_at": stmt.excluded.expires_at,
                },
            )
        )
    _record_quality(db, event, results, audit.id)
    db.commit()
    return SearchOutcome(audit.id, matches, results)
