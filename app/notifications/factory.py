"""Notification provider factory.

Provides platform-based provider lookup. Currently all platforms use OneSignal,
but the factory pattern allows easy migration to native providers (APNS, FCM,
WebPush) in the future.
"""

from functools import lru_cache
from typing import Literal

import structlog

from app.core.config import get_settings
from app.notifications.base import NotificationProvider
from app.notifications.providers.onesignal import OneSignalNotificationProvider

logger = structlog.get_logger(__name__)

# Supported platforms
Platform = Literal["ios", "android", "web"]


# Singleton provider instance (shared across all platforms currently)
_provider_instance: NotificationProvider | None = None


def get_notification_provider(platform: Platform) -> NotificationProvider:
    """Get the notification provider for a given platform.
    
    Currently all platforms use the same OneSignal provider instance.
    This factory pattern allows easy migration to platform-specific providers
    (APNS for iOS, FCM for Android, WebPush for Web) in the future.
    
    Args:
        platform: Target platform ("ios", "android", or "web")
    
    Returns:
        NotificationProvider instance for the platform
    
    Raises:
        NotificationProviderConfigError: If provider configuration is invalid
        ValueError: If platform is not supported
    
    Example future implementation:
        if platform == "ios":
            return APNSProvider()
        elif platform == "android":
            return FCMProvider()
        elif platform == "web":
            return WebPushProvider()
    """
    global _provider_instance
    
    settings = get_settings()
    
    # Check if notifications are enabled
    if not settings.NOTIFICATIONS_ENABLED:
        logger.debug("notifications_disabled", platform=platform)
        return _get_noop_provider()
    
    # Validate platform
    if platform not in ("ios", "android", "web"):
        raise ValueError(f"Unsupported notification platform: {platform}")
    
    # Currently all platforms use OneSignal
    # Future: switch statement for platform-specific providers
    if _provider_instance is None:
        _provider_instance = OneSignalNotificationProvider()
        logger.info(
            "notification_provider_created",
            provider="onesignal",
            platform=platform,
        )
    
    return _provider_instance


class NoopNotificationProvider(NotificationProvider):
    """No-op provider when notifications are disabled.
    
    Silently accepts send requests without doing anything.
    Used when NOTIFICATIONS_ENABLED=false.
    """
    
    async def send(self, token: str, payload) -> None:
        """No-op send implementation."""
        logger.debug(
            "notification_noop_send",
            token_hash=token[:8] if len(token) >= 8 else "***",
        )


_noop_provider: NoopNotificationProvider | None = None


def _get_noop_provider() -> NotificationProvider:
    """Get singleton no-op provider instance."""
    global _noop_provider
    if _noop_provider is None:
        _noop_provider = NoopNotificationProvider()
    return _noop_provider


def reset_provider() -> None:
    """Reset the cached provider instance.
    
    Useful for testing or when configuration changes.
    """
    global _provider_instance, _noop_provider
    _provider_instance = None
    _noop_provider = None
