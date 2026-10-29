import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.models.enums import ThemePreference, UserRole
from app.schemas.legal import AcceptsTerms

Password = Field(min_length=10, max_length=128)


# Where to continue after email verification (UX-003): only an event's join page, with an
# optional access code, so the emailed link can never become an open redirect.
JOIN_DESTINATION = r"^/join/[a-z0-9-]{1,80}(\?code=[A-Za-z0-9]{1,32})?$"


class SignupIn(AcceptsTerms):
    email: EmailStr
    password: str = Password
    next: str | None = Field(default=None, max_length=130, pattern=JOIN_DESTINATION)


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
    theme: ThemePreference
    new_photo_alerts: bool = True
    terms_version: str | None = None
    organizer_terms_version: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def terms_accepted(self) -> bool:
        """The current Terms of Use are accepted (else the app asks before going on)."""
        from app.services.legal import VERSIONS

        return self.terms_version == VERSIONS["terms"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def organizer_terms_accepted(self) -> bool:
        from app.services.legal import VERSIONS

        return self.organizer_terms_version == VERSIONS["organizer-terms"]


class PreferencesIn(BaseModel):
    """Only the provided preferences change."""

    theme: ThemePreference | None = None
    new_photo_alerts: bool | None = None

    @field_validator("theme", "new_photo_alerts")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Omit a preference to keep it; an explicit null is refused (defaults aren't validated).
        if value is None:
            raise ValueError("must not be null")
        return value


class MessageOut(BaseModel):
    detail: str
