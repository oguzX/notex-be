"""Notification service for sending push notifications to users.

This service handles the high-level logic of sending notifications to users,
including device lookup, concurrent delivery, and error handling.
"""

import asyncio
import hashlib
from typing import TYPE_CHECKING, cast
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.device import Device
from app.db.repositories.device_repo import DeviceRepository
from app.notifications.base import NotificationPayload
from app.notifications.errors import (
    NotificationInvalidTokenError,
    NotificationProviderConfigError,
)
from app.notifications.factory import Platform, get_notification_provider

logger = structlog.get_logger(__name__)


def _hash_token(token: str) -> str:
    """Create a short hash of token for safe logging."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


class NotificationService:
    """Service for sending push notifications to users.
    
    Handles:
    - Looking up user devices
    - Sending notifications to multiple devices concurrently
    - Handling errors and deactivating invalid tokens
    """

    def __init__(self, session: AsyncSession):
        """Initialize the notification service.
        
        Args:
            session: Database session for device queries and updates
        """
        self.session = session
        self.device_repo = DeviceRepository(session)

    async def send_to_user(
        self,
        user_id: UUID,
        payload: NotificationPayload,
    ) -> dict[str, int]:
        """Send a notification to all active devices of a user.
        
        Sends notifications concurrently to all active devices. Handles
        errors gracefully - if some devices fail, others still receive
        the notification.
        
        If a device token is found to be invalid, it will be deactivated
        automatically.
        
        Args:
            user_id: Target user ID
            payload: Notification payload (title, body, optional data)
        
        Returns:
            Dict with delivery statistics:
            - "total": Total active devices for user
            - "sent": Successfully sent count
            - "failed": Failed delivery count
            - "deactivated": Devices deactivated due to invalid tokens
        
        Note:
            Does not raise exceptions for delivery failures. Check the
            returned statistics to determine success rate.
        """
        # Get all active devices for the user
        devices = await self.device_repo.get_by_user_id(user_id, active_only=True)
        
        if not devices:
            logger.debug(
                "notification_no_devices",
                user_id=str(user_id),
            )
            return {"total": 0, "sent": 0, "failed": 0, "deactivated": 0}
        
        logger.info(
            "notification_sending",
            user_id=str(user_id),
            device_count=len(devices),
            title=payload.title[:50],
        )
        
        # Group devices by platform for potential future optimization
        devices_by_platform: dict[str, list[Device]] = {}
        for device in devices:
            if device.platform not in devices_by_platform:
                devices_by_platform[device.platform] = []
            devices_by_platform[device.platform].append(device)
        
        # Send to all devices concurrently
        tasks = []
        for platform, platform_devices in devices_by_platform.items():
            for device in platform_devices:
                tasks.append(
                    self._send_to_device(device, payload)
                )
        
        # Wait for all sends, allowing exceptions to be captured
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        sent = 0
        failed = 0
        deactivated = 0
        
        for i, result in enumerate(results):
            device = devices[i]
            
            if result is None:
                # Success (no exception)
                sent += 1
            elif isinstance(result, NotificationInvalidTokenError):
                # Invalid token - deactivate device
                await self.device_repo.deactivate(device.id)
                deactivated += 1
                failed += 1
                logger.warning(
                    "notification_device_deactivated",
                    device_id=str(device.id),
                    platform=device.platform,
                    token_hash=_hash_token(device.notification_token),
                )
            elif isinstance(result, NotificationProviderConfigError):
                # Config error - log and fail all (but don't re-raise)
                failed += 1
                logger.error(
                    "notification_config_error",
                    error=str(result),
                )
            elif isinstance(result, Exception):
                # Other error - log and continue
                failed += 1
                logger.warning(
                    "notification_delivery_failed",
                    device_id=str(device.id),
                    platform=device.platform,
                    error=str(result),
                )
        
        logger.info(
            "notification_batch_complete",
            user_id=str(user_id),
            total=len(devices),
            sent=sent,
            failed=failed,
            deactivated=deactivated,
        )
        
        return {
            "total": len(devices),
            "sent": sent,
            "failed": failed,
            "deactivated": deactivated,
        }

    async def _send_to_device(
        self,
        device: Device,
        payload: NotificationPayload,
    ) -> None:
        """Send notification to a single device.
        
        Args:
            device: Target device
            payload: Notification payload
        
        Raises:
            NotificationInvalidTokenError: If token is invalid
            NotificationProviderError: If delivery fails
            NotificationProviderConfigError: If provider is misconfigured
        """
        # Cast to Platform type - validated on device creation
        platform = cast(Platform, device.platform)
        provider = get_notification_provider(platform)
        await provider.send(device.notification_token, payload)

    async def send_to_devices(
        self,
        device_ids: list[UUID],
        payload: NotificationPayload,
    ) -> dict[str, int]:
        """Send notification to specific devices by ID.
        
        Useful when you want to target specific devices rather than
        all devices for a user.
        
        Args:
            device_ids: List of device UUIDs to target
            payload: Notification payload
        
        Returns:
            Delivery statistics dict (same as send_to_user)
        """
        # Fetch devices
        devices = []
        for device_id in device_ids:
            device = await self.device_repo.get_by_id(device_id)
            if device and device.is_active:
                devices.append(device)
        
        if not devices:
            return {"total": 0, "sent": 0, "failed": 0, "deactivated": 0}
        
        # Send concurrently
        tasks = [self._send_to_device(d, payload) for d in devices]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        sent = 0
        failed = 0
        deactivated = 0
        
        for i, result in enumerate(results):
            device = devices[i]
            
            if result is None:
                sent += 1
            elif isinstance(result, NotificationInvalidTokenError):
                await self.device_repo.deactivate(device.id)
                deactivated += 1
                failed += 1
            elif isinstance(result, Exception):
                failed += 1
        
        return {
            "total": len(devices),
            "sent": sent,
            "failed": failed,
            "deactivated": deactivated,
        }
