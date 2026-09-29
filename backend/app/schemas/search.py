import datetime as dt
import uuid

from typing import Literal

from pydantic import BaseModel, Field


class ConsentInfo(BaseModel):
    version: str
    grant_days: int
    given: bool
    given_at: dt.datetime | None


class ConsentIn(BaseModel):
    version: str = Field(max_length=40)


Tier = Literal["best", "possible"]
Verdict = Literal["me", "not_me"]


class CaptureTokenOut(BaseModel):
    token: str
    expires_in: int


class MatchOut(BaseModel):
    id: uuid.UUID
    similarity: float
    tier: Tier
    width: int | None
    height: int | None


class ShotQualityOut(BaseModel):
    shot: str
    score: int


class SearchOut(BaseModel):
    search_id: int
    matches: list[MatchOut]
    quality: list[ShotQualityOut]


class SelfieRejectionOut(BaseModel):
    code: str
    message: str
    shot: str


class MyPhotoOut(BaseModel):
    id: uuid.UUID
    width: int | None
    height: int | None
    similarity: float | None
    tier: Tier | None  # None for the user's own uploads
    verdict: Verdict | None
    expires_at: dt.datetime | None


class FeedbackIn(BaseModel):
    photo_id: uuid.UUID
    verdict: Verdict


class BandOut(BaseModel):
    lower: float
    upper: float
    me: int
    not_me: int
    wrong_rate: float | None


class MatchQualityOut(BaseModel):
    searches: int
    feedback: int
    missing_reports: int
    bands: list[BandOut]
    current_possible: float
    current_best: float
    suggested_threshold: float | None
    suggestion_note: str
    quality_histogram: list[int]
    rejection_reasons: dict[str, int]
    shots_total: int
    shots_passed: int


class EventMatchQualityOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    searches: int
    feedback: int
    wrong_rate: float | None
    missing_reports: int


class GlobalMatchQualityOut(MatchQualityOut):
    events: list[EventMatchQualityOut]


class DownloadIn(BaseModel):
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class DownloadOut(BaseModel):
    url: str
    expires_in: int
    count: int
