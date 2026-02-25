"""Pydantic schemas for user settings, metas, and options."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.user_settings_validators import validate_iana_timezone


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------


class TimezoneField(BaseModel):
    """Mixin-style schema with a validated timezone field."""

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


# ---------------------------------------------------------------------------
# Meta schemas
# ---------------------------------------------------------------------------


class MetaResponse(BaseModel):
    """Response for a single meta definition."""

    id: UUID
    key: str
    name: str
    type: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MetasUpdatePayload(BaseModel):
    """Payload for attaching/detaching metas by key."""

    attach: list[str] = Field(default_factory=list, description="Meta keys to attach")
    detach: list[str] = Field(default_factory=list, description="Meta keys to detach")


# ---------------------------------------------------------------------------
# User options
# ---------------------------------------------------------------------------


class UserOptionsResponse(BaseModel):
    """Response for user options."""

    settings_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# PATCH /user/update  request / response
# ---------------------------------------------------------------------------


class UserUpdateRequest(BaseModel):
    """Request schema for PATCH /user/update.

    All fields are optional.  Only supplied fields are applied.
    """

    timezone: str | None = Field(
        default=None,
        max_length=64,
        description="IANA timezone name, e.g. 'Europe/Istanbul'",
    )
    metas: MetasUpdatePayload | None = Field(
        default=None,
        description="Attach/detach meta flags by key",
    )
    options: dict[str, Any] | None = Field(
        default=None,
        description="Deep-merge patch for user options JSON",
    )

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_iana_timezone(v)
        return v


class UserMetaItem(BaseModel):
    """Single attached meta in the response."""

    key: str
    name: str
    type: str
    attached_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateResponse(BaseModel):
    """Response schema for PATCH /user/update."""

    user_id: str
    timezone: str | None = None
    metas: list[UserMetaItem] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
