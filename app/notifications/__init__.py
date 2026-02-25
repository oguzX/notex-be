"""Notification module for push notifications.

This module provides a platform-agnostic notification system that currently
uses OneSignal as the provider for all platforms (iOS, Android, Web).
"""

from app.notifications.base import NotificationPayload, NotificationProvider
from app.notifications.errors import (
    NotificationError,
    NotificationInvalidTokenError,
    NotificationProviderConfigError,
    NotificationProviderError,
)
from app.notifications.factory import Platform, get_notification_provider
from app.notifications.service import NotificationService

__all__ = [
    # Base types
    "NotificationPayload",
    "NotificationProvider",
    "Platform",
    # Errors
    "NotificationError",
    "NotificationInvalidTokenError",
    "NotificationProviderConfigError",
    "NotificationProviderError",
    # Factory
    "get_notification_provider",
    # Service
    "NotificationService",
]
