"""Base notification provider interface and types."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class NotificationPayload(BaseModel):
    """Payload for push notifications.
    
    Attributes:
        title: Notification title/heading
        body: Notification body/content text
        data: Optional additional data to include with the notification
              (passed to the app when notification is tapped)
    """

    title: str = Field(..., description="Notification title/heading")
    body: str = Field(..., description="Notification body/content")
    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional additional data payload for the notification",
    )


class NotificationProvider(ABC):
    """Abstract base class for notification providers.
    
    All notification providers (OneSignal, APNS, FCM, WebPush, etc.) must
    implement this interface.
    """

    @abstractmethod
    async def send(self, token: str, payload: NotificationPayload) -> None:
        """Send a notification to a specific device.
        
        Args:
            token: The device notification token (e.g., OneSignal player_id,
                   APNS device token, FCM registration token)
            payload: The notification payload containing title, body, and optional data
        
        Raises:
            NotificationInvalidTokenError: If the token is invalid or device is unsubscribed
            NotificationProviderError: If there's a provider error during delivery
            NotificationProviderConfigError: If the provider is misconfigured
        """
        pass
