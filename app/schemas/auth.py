"""Authentication schemas."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.user_settings_validators import validate_iana_timezone


class GuestRegisterRequest(BaseModel):
    """Request schema for guest registration."""

    client_uuid: UUID = Field(..., description="Client-generated UUID for guest identification")
    timezone: str | None = Field(
        default=None,
        max_length=64,
        description="IANA timezone name, e.g. 'Europe/Istanbul'",
    )

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_iana_timezone(v)
        return v


class RefreshRequest(BaseModel):
    """Request schema for token refresh."""

    refresh_token: str = Field(..., description="Refresh token to exchange for new tokens")


class TokenResponse(BaseModel):
    """Response schema for token operations."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="Opaque refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration in seconds")
    user_id: str = Field(..., description="User ID")
    timezone: str | None = Field(default=None, description="User timezone (IANA)")
