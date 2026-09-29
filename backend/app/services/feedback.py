"""Match feedback ("This is me" / "Not me" / "Photos of me are missing") and the
statistics that turn it into a threshold suggestion.

Feedback is recorded from server-side facts (the user's grant: which face matched, at
what similarity, in which search). Nothing biometric is stored, and the links to the
user/face/photo/search are removed by `anonymize_feedback` when the event's face data
expires, consent is withdrawn, or the account is deleted.
"""

import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Event, FeedbackVerdict, MatchFeedback, SearchAudit, SearchGrant, SelfieQuality, User

# Similarity bands for the wrong-match chart.
BAND_WIDTH = 0.05
BAND_START = 0.30
MIN_FEEDBACK_FOR_SUGGESTION = 30
TARGET_PRECISION = 0.90


def record_verdict(db: Session, user: User, event: Event, photo_id: uuid.UUID, verdict: FeedbackVerdict) -> MatchFeedback:
    if verdict == FeedbackVerdict.missing:
        raise ValueError("use record_missing")
    grant = db.scalar(
        select(SearchGrant).where(
            SearchGrant.user_id == user.id,
            SearchGrant.event_id == event.id,
            SearchGrant.photo_id == photo_id,
            SearchGrant.expires_at > utcnow(),
        )
    )
    if grant is None:
        # You can only judge matches you were actually shown.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This photo isn't one of your matches")

    stmt = insert(MatchFeedback).values(
        id=uuid.uuid4(),
        search_id=grant.search_id,
        user_id=user.id,
        event_id=event.id,
        photo_id=photo_id,
        face_id=grant.face_id,
        similarity_score=grant.similarity,
        verdict=verdict,
    )
    row_id = db.scalar(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "photo_id"],
            index_where=(MatchFeedback.user_id.is_not(None)) & (MatchFeedback.photo_id.is_not(None)),
            set_={"verdict": verdict, "created_at": func.now(), "similarity_score": grant.similarity},
        ).returning(MatchFeedback.id)
    )
    if verdict == FeedbackVerdict.not_me:
        # Stop showing (and allowing downloads of) a stranger's photo.
        db.execute(delete(SearchGrant).where(SearchGrant.user_id == user.id, SearchGrant.photo_id == photo_id))
    db.commit()
    return db.get(MatchFeedback, row_id)  # type: ignore[return-value]


def record_missing(db: Session, user: User, event: Event) -> MatchFeedback:
    last_search = db.scalar(
        select(SearchAudit.id)
        .where(SearchAudit.user_id == user.id, SearchAudit.event_id == event.id)
        .order_by(SearchAudit.created_at.desc())
        .limit(1)
    )
    row = MatchFeedback(search_id=last_search, user_id=user.id, event_id=event.id, verdict=FeedbackVerdict.missing)
    db.add(row)
    db.commit()
    return row


def anonymize_feedback(db: Session, *where: ColumnElement[bool]) -> int:
    """Drop every link to a person, face, photo or search; keep verdict/similarity/event."""
    return (
        db.execute(
            update(MatchFeedback)
            .where(*where)
            .values(user_id=None, face_id=None, photo_id=None, search_id=None)
        ).rowcount
        or 0
    )


# --- Statistics ------------------------------------------------------------------------


@dataclass
class Band:
    lower: float
    upper: float
    me: int = 0
    not_me: int = 0

    @property
    def total(self) -> int:
        return self.me + self.not_me

    @property
    def wrong_rate(self) -> float | None:
        return round(self.not_me / self.total, 3) if self.total else None


@dataclass
class MatchQuality:
    searches: int = 0
    feedback: int = 0
    missing_reports: int = 0
    bands: list[Band] = field(default_factory=list)
    current_possible: float = 0.0
    current_best: float = 0.0
    suggested_threshold: float | None = None
    suggestion_note: str = ""
    quality_histogram: list[int] = field(default_factory=lambda: [0] * 10)  # scores 0-9, 10-19, …
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    shots_total: int = 0
    shots_passed: int = 0


def _bands() -> list[Band]:
    bands, lower = [], BAND_START
    while lower < 1.0 - 1e-9:
        bands.append(Band(round(lower, 2), round(min(lower + BAND_WIDTH, 1.0), 2)))
        lower += BAND_WIDTH
    return bands


def suggest_threshold(bands: list[Band]) -> tuple[float | None, str]:
    """Lowest band edge t such that, among all rated matches with similarity >= t, at
    least TARGET_PRECISION were confirmed as "me". Needs MIN_FEEDBACK_FOR_SUGGESTION."""
    total = sum(b.total for b in bands)
    if total < MIN_FEEDBACK_FOR_SUGGESTION:
        return None, f"Not enough feedback yet ({total} of {MIN_FEEDBACK_FOR_SUGGESTION} ratings)."
    for i, band in enumerate(bands):
        above = bands[i:]
        me = sum(b.me for b in above)
        rated = sum(b.total for b in above)
        if rated and me / rated >= TARGET_PRECISION:
            return band.lower, (
                f"At ≥ {band.lower:.2f}, {me} of {rated} rated matches ({me / rated:.0%}) were confirmed. "
                f"Target: {TARGET_PRECISION:.0%}."
            )
    return None, f"No cutoff reaches {TARGET_PRECISION:.0%} confirmed matches; consider raising the threshold."


def match_quality(db: Session, event_id: uuid.UUID | None) -> MatchQuality:
    """Stats for one event, or across all events when event_id is None."""
    s = get_settings()
    scope_fb = [MatchFeedback.event_id == event_id] if event_id else []
    scope_sq = [SelfieQuality.event_id == event_id] if event_id else []
    scope_sa = [SearchAudit.event_id == event_id] if event_id else []
    out = MatchQuality(current_possible=s.face_match_threshold, current_best=s.match_best_threshold, bands=_bands())

    out.searches = db.scalar(select(func.count()).select_from(SearchAudit).where(*scope_sa)) or 0
    rows = db.execute(
        select(MatchFeedback.verdict, MatchFeedback.similarity_score).where(
            *scope_fb, MatchFeedback.verdict != FeedbackVerdict.missing, MatchFeedback.similarity_score.is_not(None)
        )
    ).all()
    for verdict, sim in rows:
        idx = min(max(int((sim - BAND_START) / BAND_WIDTH), 0), len(out.bands) - 1)
        if verdict == FeedbackVerdict.me:
            out.bands[idx].me += 1
        else:
            out.bands[idx].not_me += 1
    out.feedback = len(rows)
    out.missing_reports = (
        db.scalar(
            select(func.count()).select_from(MatchFeedback).where(*scope_fb, MatchFeedback.verdict == FeedbackVerdict.missing)
        )
        or 0
    )
    out.suggested_threshold, out.suggestion_note = suggest_threshold(out.bands)

    for score, passed, reason in db.execute(
        select(SelfieQuality.score, SelfieQuality.passed, SelfieQuality.reason).where(*scope_sq)
    ).all():
        out.quality_histogram[min(score // 10, 9)] += 1
        out.shots_total += 1
        if passed:
            out.shots_passed += 1
        elif reason:
            out.rejection_reasons[reason] = out.rejection_reasons.get(reason, 0) + 1
    return out
