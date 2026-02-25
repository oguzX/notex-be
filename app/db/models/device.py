"""Device model for push notification registration.

Stores device information and notification tokens for push notification delivery.
The notification_token field stores the OneSignal player_id (subscription ID),
which is the unique identifier for a device subscription in OneSignal.

Note on token field naming:
- Field is named `notification_token` for backward compatibility
- Actually stores OneSignal player_id / subscription_id
- Token is never logged in full; use hash/prefix for logging
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User


class Device(Base):
    """Device model for push notification tokens.
    
    Each device represents a unique app installation that can receive
    push notifications. A user can have multiple devices (phone, tablet, web).
    
    Attributes:
        id: Unique device identifier
        user_id: Owner user ID (can be guest or registered)
        platform: Device platform ("ios", "android", "web")
        notification_token: OneSignal player_id / subscription_id
            - Stores the OneSignal subscription identifier
            - Used to target specific devices for push notifications
            - Named `notification_token` for API compatibility
        device_name: Optional human-readable device name/identifier
        is_active: Whether this device can receive notifications
            - Set to False when token becomes invalid/unsubscribed
        created_at: When the device was registered
        updated_at: Last update timestamp
    """

    __tablename__ = "devices"
    
    __table_args__ = (
        # Each user can only have one device per platform+token combination
        UniqueConstraint(
            "user_id",
            "notification_token",
            name="uq_devices_user_id_notification_token",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Platform: "ios", "android", or "web"
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # notification_token stores the OneSignal player_id (subscription ID)
    # This is the unique identifier for the device in OneSignal's system
    # Note: Never log this value in full - use hash or prefix only
    notification_token: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Optional human-readable device identifier (e.g., "iPhone 15 Pro")
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # Active flag - set to False when token becomes invalid
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="devices")

    def __repr__(self) -> str:
        # Never include token in repr for security
        token_prefix = self.notification_token[:8] if self.notification_token else "None"
        return (
            f"<Device(id={self.id}, user_id={self.user_id}, "
            f"platform={self.platform}, token={token_prefix}..., is_active={self.is_active})>"
        )
