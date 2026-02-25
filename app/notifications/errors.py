"""Notification error types.

These exceptions are raised by notification providers and the notification service
to handle various error conditions during push notification delivery.
"""


class NotificationError(Exception):
    """Base exception for all notification-related errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotificationProviderError(NotificationError):
    """Raised when the notification provider encounters an error during delivery.
    
    This includes network errors, timeouts, rate limits, and general API errors
    that are not specifically related to invalid tokens.
    """

    error_code = "NOTIFICATION_PROVIDER_ERROR"


class NotificationInvalidTokenError(NotificationError):
    """Raised when the notification token is invalid or the device is unsubscribed.
    
    When this error is raised, the corresponding device should be marked as
    inactive (is_active=False) to prevent future delivery attempts.
    """

    error_code = "NOTIFICATION_INVALID_TOKEN"


class NotificationProviderConfigError(NotificationError):
    """Raised when the notification provider is misconfigured.
    
    This is raised when required configuration (API keys, app IDs, etc.) is
    missing or invalid. Should cause the provider to fail early at initialization.
    """

    error_code = "NOTIFICATION_CONFIG_ERROR"
