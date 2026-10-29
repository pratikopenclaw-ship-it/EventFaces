from typing import Literal

from pydantic import BaseModel, Field


class PhotoAlertIn(BaseModel):
    enabled: bool


class PhotoAlertOut(BaseModel):
    """`subscribed`: the user has searched the event (alerts exist only after a search)."""

    subscribed: bool
    enabled: bool


class UnsubscribeIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    scope: Literal["event", "all"]
