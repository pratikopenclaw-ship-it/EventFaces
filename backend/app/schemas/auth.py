import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole

Password = Field(min_length=10, max_length=128)


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Password


class LoginIn(BaseModel):
    # Plain string: login only looks up an existing account, so it shouldn't reject
    # addresses that stricter validation (e.g. reserved domains) might refuse.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    email_verified_at: datetime | None
    created_at: datetime


class MessageOut(BaseModel):
    detail: str
