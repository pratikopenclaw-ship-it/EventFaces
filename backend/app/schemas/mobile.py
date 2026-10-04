import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.auth import UserOut
from app.schemas.legal import AcceptsTerms

# base64 of a 65-byte X9.63 point (88 chars) / a DER ECDSA signature (<= 72 bytes -> 96 chars)
PUBLIC_KEY = Field(min_length=88, max_length=88, pattern=r"^[A-Za-z0-9+/]+={0,2}$")
SIGNATURE = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9+/]+={0,2}$")
OPAQUE_TOKEN = Field(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    platform: Literal["ios"] = "ios"
    public_key: str = PUBLIC_KEY


class CodeRequestIn(BaseModel):
    email: EmailStr


class CodeVerifyIn(AcceptsTerms):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    device: DeviceIn


class MagicLinkIn(AcceptsTerms):
    token: str = OPAQUE_TOKEN
    device: DeviceIn


class RefreshIn(BaseModel):
    refresh_token: str = OPAQUE_TOKEN
    device_id: uuid.UUID
    ts: int = Field(ge=0, le=10**11)
    signature: str = SIGNATURE
    # App Attest assertion over the refresh message (report-only; see services/app_attest).
    assertion: str | None = Field(default=None, max_length=1400, pattern=r"^[A-Za-z0-9+/]+={0,2}$")


class AttestChallengeOut(BaseModel):
    challenge: str  # base64; attest over SHA-256 of these bytes


class AttestIn(BaseModel):
    key_id: str = Field(min_length=44, max_length=44, pattern=r"^[A-Za-z0-9+/]+={0,2}$")
    attestation: str = Field(min_length=8, max_length=22000, pattern=r"^[A-Za-z0-9+/]+={0,2}$")


class AttestOut(BaseModel):
    status: Literal["verified", "failed"]


class MobileTokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # nosec B105 - OAuth token type name, not a secret
    expires_in: int
    device_id: uuid.UUID
    user: UserOut


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    platform: str
    app_version: str
    created_at: datetime
    last_seen_at: datetime
    current: bool = False


class PushTokenIn(BaseModel):
    token: str = Field(min_length=64, max_length=200, pattern=r"^[0-9a-fA-F]+$")
    env: Literal["sandbox", "production"]


class AppConfigOut(BaseModel):
    min_supported_version: str
    latest_version: str
    update_url: str
    app_attest: bool  # the server checks App Attest (report-only for now)
