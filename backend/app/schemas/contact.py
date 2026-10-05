from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    topic: Literal["organizer", "attendee", "privacy", "other"]
    message: str = Field(min_length=10, max_length=5000)
    # Honeypot: hidden from people, filled in by bots. A filled one is accepted and dropped.
    website: str = Field(default="", max_length=200)


class ContactOut(BaseModel):
    status: Literal["sent"]
