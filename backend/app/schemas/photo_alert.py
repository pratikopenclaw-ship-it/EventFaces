from pydantic import BaseModel


class PhotoAlertIn(BaseModel):
    enabled: bool


class PhotoAlertOut(BaseModel):
    """`subscribed`: the user has searched the event (alerts exist only after a search)."""

    subscribed: bool
    enabled: bool
