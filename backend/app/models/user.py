import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func, true
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import ThemePreference, TokenKind, UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    # NULL for accounts created by passwordless (emailed code) sign-in in the app; password
    # login then fails through the dummy-hash path, like an unknown email.
    password_hash: Mapped[str | None] = mapped_column(String)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False, default=UserRole.attendee
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Explicit consent (GDPR Art. 9(2)(a)) to biometric processing for selfie search.
    face_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    face_consent_version: Mapped[str | None] = mapped_column(String(40))
    # Colour theme; mirrored into the ef_theme cookie so pages render in it server-side.
    theme: Mapped[ThemePreference] = mapped_column(
        Enum(ThemePreference, name="theme_preference"), nullable=False, default=ThemePreference.system,
        server_default=ThemePreference.system.value,
    )
    # Account-wide switch for new-photo alert emails and pushes (services/photo_alerts.py).
    new_photo_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    # Current accepted versions of the Terms of Use / Organizer Terms (services/legal.py);
    # the full history with time and channel is in legal_acceptances.
    terms_version: Mapped[str | None] = mapped_column(String(20))
    organizer_terms_version: Mapped[str | None] = mapped_column(String(20))

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class AuthToken(Base):
    """Single-use or revocable opaque tokens. Only the SHA-256 hash is stored."""

    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[TokenKind] = mapped_column(Enum(TokenKind, name="token_kind"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Refresh tokens only: the login session this token belongs to. Rotation keeps it;
    # access JWTs carry it as "sid" and die as soon as the session has no live token.
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LegalAcceptance(Base):
    """Proof of acceptance: who accepted which version of which document, when and where.
    Append-only; deleted with the account."""

    __tablename__ = "legal_acceptances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document: Mapped[str] = mapped_column(String(32), nullable=False)  # terms | organizer-terms
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    locale: Mapped[str] = mapped_column(String(5), nullable=False)  # language the text was shown in
    channel: Mapped[str] = mapped_column(String(8), nullable=False)  # web | ios
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
