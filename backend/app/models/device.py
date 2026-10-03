import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Device(Base):
    """A signed-in mobile app install. Its login session is `session_id` (the refresh-token
    family in auth_tokens); refreshing it requires a signature by `public_key`, a P-256 key
    that never leaves the device's Secure Enclave, so a copied refresh token is useless."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key: Mapped[str] = mapped_column(String(128), nullable=False)  # base64 X9.63 point
    apns_token: Mapped[str | None] = mapped_column(String(200))
    apns_env: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # App Attest (report-only, services/app_attest.py). Statuses and reasons are short
    # codes; the key id is unique so one attested key can't be shared between accounts.
    attest_key_id: Mapped[str | None] = mapped_column(String(44), unique=True)
    attest_public_key: Mapped[str | None] = mapped_column(String(128))
    attest_counter: Mapped[int | None] = mapped_column(BigInteger)
    attest_status: Mapped[str | None] = mapped_column(String(16))  # verified | failed
    attest_reason: Mapped[str | None] = mapped_column(String(40))
    attest_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assertion_status: Mapped[str | None] = mapped_column(String(16))  # ok | failed | missing
    assertion_reason: Mapped[str | None] = mapped_column(String(40))
