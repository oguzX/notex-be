"""Device schemas for push notification registration."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


Platform = Literal["ios", "android", "web"]


class DeviceRegisterRequest(BaseModel):
    """Request schema for device registration.
    
    The notification_token is the OneSignal player_id (subscription ID),
    which is the unique identifier for a device subscription in OneSignal.
    """

    platform: Platform = Field(
        ...,
        description='Device platform: "ios", "android", or "web"',
    )
    notification_token: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "OneSignal player_id (subscription ID). "
            "This is the unique identifier for the device in OneSignal."
        ),
    )
    device_name: str | None = Field(
        default=None,
        max_length=100,
        description='Optional human-readable device name (e.g., "iPhone 15 Pro")',
    )


class DeviceResponse(BaseModel):
    """Response schema for device operations.
    
    Note: notification_token is intentionally NOT included in the response
    for security reasons.
    """

    id: UUID = Field(..., description="Device ID")
    platform: Platform = Field(..., description="Device platform")
    device_name: str | None = Field(None, description="Device name")
    is_active: bool = Field(..., description="Whether the device can receive notifications")
    created_at: datetime = Field(..., description="Registration timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    """Response schema for listing user devices."""

    devices: list[DeviceResponse] = Field(..., description="List of registered devices")
    count: int = Field(..., description="Total number of devices")
