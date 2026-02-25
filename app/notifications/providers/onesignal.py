"""OneSignal notification provider implementation.

This provider sends push notifications via the OneSignal REST API.
It supports iOS, Android, and Web platforms using the same API.

The notification_token field stores the OneSignal player_id (subscription ID),
which is a unique identifier for each device subscription in OneSignal.
"""

import hashlib
from typing import Any

import httpx
import structlog

from app.core.config import get_settings
from app.notifications.base import NotificationPayload, NotificationProvider
from app.notifications.errors import (
    NotificationInvalidTokenError,
    NotificationProviderConfigError,
    NotificationProviderError,
)

logger = structlog.get_logger(__name__)

# Timeout for OneSignal API requests (seconds)
ONESIGNAL_TIMEOUT = 10.0

# Max retry attempts for transient errors
MAX_RETRIES = 2

# Backoff delays between retries (seconds)
RETRY_DELAYS = [0.5, 1.0]


def _hash_token(token: str) -> str:
    """Create a short hash of token for safe logging.
    
    Args:
        token: The notification token (OneSignal player_id)
    
    Returns:
        First 8 characters of SHA-256 hash for logging
    """
    return hashlib.sha256(token.encode()).hexdigest()[:8]


def _is_invalid_token_error(response: httpx.Response) -> bool:
    """Check if the OneSignal response indicates an invalid/unsubscribed token.
    
    OneSignal returns various indicators that a player_id is no longer valid:
    - 400 with "invalid_player_ids" in response
    - 400 with "errors" containing player ID related messages
    - 200 with "errors" or "invalid_player_ids" array containing the token
    
    Args:
        response: The HTTP response from OneSignal
    
    Returns:
        True if the error indicates an invalid token
    """
    try:
        data = response.json()
    except Exception:
        return False
    
    # Check for invalid_player_ids array in response
    invalid_ids = data.get("invalid_player_ids", [])
    if invalid_ids:
        return True
    
    # Check for errors array with token-related messages
    errors = data.get("errors", [])
    if isinstance(errors, list):
        for error in errors:
            if isinstance(error, str):
                error_lower = error.lower()
                if any(
                    indicator in error_lower
                    for indicator in [
                        "invalid player",
                        "invalid subscription",
                        "not subscribed",
                        "player not found",
                        "no subscribed players",
                        "all included players are not subscribed",
                    ]
                ):
                    return True
    
    # Check error dict format (older API responses)
    if isinstance(errors, dict):
        for key, value in errors.items():
            if "player" in key.lower() or "subscription" in key.lower():
                return True
    
    return False


def _is_retryable_error(response: httpx.Response | None, exception: Exception | None) -> bool:
    """Check if the error is transient and safe to retry.
    
    Args:
        response: HTTP response if available
        exception: Exception if request failed
    
    Returns:
        True if the error is transient and should be retried
    """
    # Network errors are retryable
    if exception is not None:
        if isinstance(exception, (httpx.TimeoutException, httpx.ConnectError)):
            return True
    
    # 5xx errors are server-side issues, retryable
    if response is not None and 500 <= response.status_code < 600:
        return True
    
    return False


class OneSignalNotificationProvider(NotificationProvider):
    """OneSignal notification provider.
    
    Sends push notifications via OneSignal REST API. Supports all platforms
    (iOS, Android, Web) using the same API with player_id targeting.
    
    Configuration:
        - ONESIGNAL_APP_ID: Your OneSignal App ID
        - ONESIGNAL_REST_API_KEY: Your OneSignal REST API Key (server key)
        - ONESIGNAL_API_BASE: Optional custom API base URL
    
    The notification_token stored in Device model is the OneSignal player_id
    (also called subscription_id), which uniquely identifies a device
    subscription in OneSignal.
    """

    def __init__(self):
        """Initialize the OneSignal provider.
        
        Validates that required configuration is present.
        
        Raises:
            NotificationProviderConfigError: If required config is missing
        """
        self.settings = get_settings()
        self._validate_config()
        
        self.app_id = self.settings.ONESIGNAL_APP_ID
        self.api_key = self.settings.ONESIGNAL_REST_API_KEY
        self.api_base = self.settings.ONESIGNAL_API_BASE.rstrip("/")
        
        logger.info(
            "onesignal_provider_initialized",
            api_base=self.api_base,
        )
    
    def _validate_config(self) -> None:
        """Validate OneSignal configuration.
        
        Raises:
            NotificationProviderConfigError: If required config is missing
        """
        missing = []
        
        if not self.settings.ONESIGNAL_APP_ID:
            missing.append("ONESIGNAL_APP_ID")
        
        if not self.settings.ONESIGNAL_REST_API_KEY:
            missing.append("ONESIGNAL_REST_API_KEY")
        
        if missing:
            raise NotificationProviderConfigError(
                f"Missing required OneSignal configuration: {', '.join(missing)}",
                details={"missing_keys": missing},
            )
    
    async def send(self, token: str, payload: NotificationPayload) -> None:
        """Send a notification to a device via OneSignal.
        
        Args:
            token: OneSignal player_id (subscription ID) for the target device
            payload: Notification payload with title, body, and optional data
        
        Raises:
            NotificationInvalidTokenError: If the player_id is invalid/unsubscribed
            NotificationProviderError: If there's a delivery error
        """
        token_hash = _hash_token(token)
        
        # Build OneSignal request payload
        request_payload = self._build_request_payload(token, payload)
        
        last_error: Exception | None = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._make_request(request_payload)
                
                # Check for success
                if response.status_code == 200:
                    # Check if response indicates success
                    data = response.json()
                    
                    # Even 200 responses can contain invalid_player_ids
                    if _is_invalid_token_error(response):
                        logger.warning(
                            "onesignal_invalid_token",
                            token_hash=token_hash,
                            response=data,
                        )
                        raise NotificationInvalidTokenError(
                            f"Invalid or unsubscribed player_id: {token_hash}...",
                            details={"token_hash": token_hash, "response": data},
                        )
                    
                    logger.info(
                        "onesignal_notification_sent",
                        token_hash=token_hash,
                        recipients=data.get("recipients", 0),
                    )
                    return
                
                # Check for invalid token errors (4xx)
                if _is_invalid_token_error(response):
                    logger.warning(
                        "onesignal_invalid_token",
                        token_hash=token_hash,
                        status_code=response.status_code,
                    )
                    raise NotificationInvalidTokenError(
                        f"Invalid or unsubscribed player_id: {token_hash}...",
                        details={
                            "token_hash": token_hash,
                            "status_code": response.status_code,
                        },
                    )
                
                # Check for retryable errors
                if _is_retryable_error(response, None):
                    last_error = NotificationProviderError(
                        f"OneSignal server error: {response.status_code}",
                        details={"status_code": response.status_code},
                    )
                    if attempt < MAX_RETRIES:
                        await self._backoff(attempt)
                        continue
                    raise last_error
                
                # Non-retryable 4xx error
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"raw": response.text[:200]}
                
                logger.warning(
                    "onesignal_client_error",
                    token_hash=token_hash,
                    status_code=response.status_code,
                    error_data=error_data,
                )
                raise NotificationProviderError(
                    f"OneSignal request failed: {response.status_code}",
                    details={
                        "status_code": response.status_code,
                        "error": error_data,
                    },
                )
                
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "onesignal_request_retry",
                        token_hash=token_hash,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    await self._backoff(attempt)
                    continue
                
                logger.warning(
                    "onesignal_request_failed",
                    token_hash=token_hash,
                    error=str(e),
                )
                raise NotificationProviderError(
                    f"OneSignal request failed after {MAX_RETRIES + 1} attempts: {e}",
                    details={"error_type": type(e).__name__},
                )
            
            except (NotificationInvalidTokenError, NotificationProviderError):
                # Re-raise notification errors without modification
                raise
            
            except Exception as e:
                logger.error(
                    "onesignal_unexpected_error",
                    token_hash=token_hash,
                    error=str(e),
                )
                raise NotificationProviderError(
                    f"Unexpected error sending notification: {e}",
                    details={"error_type": type(e).__name__},
                )
    
    def _build_request_payload(
        self,
        token: str,
        payload: NotificationPayload,
    ) -> dict[str, Any]:
        """Build the OneSignal API request payload.
        
        Args:
            token: OneSignal player_id
            payload: Notification payload
        
        Returns:
            Dict ready to be sent to OneSignal API
        """
        request = {
            "app_id": self.app_id,
            "include_player_ids": [token],
            "headings": {"en": payload.title},
            "contents": {"en": payload.body},
        }
        
        if payload.data:
            request["data"] = payload.data
        
        return request
    
    async def _make_request(self, payload: dict[str, Any]) -> httpx.Response:
        """Make HTTP request to OneSignal API.
        
        Args:
            payload: Request payload
        
        Returns:
            HTTP response
        """
        async with httpx.AsyncClient(timeout=ONESIGNAL_TIMEOUT) as client:
            return await client.post(
                f"{self.api_base}/notifications",
                headers={
                    "Authorization": f"Basic {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    
    async def _backoff(self, attempt: int) -> None:
        """Wait before retrying.
        
        Args:
            attempt: Current attempt number (0-indexed)
        """
        import asyncio
        
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        await asyncio.sleep(delay)
