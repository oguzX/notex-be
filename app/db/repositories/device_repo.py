"""Device repository for notification token management."""

import hashlib
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.device import Device

logger = structlog.get_logger(__name__)


def _hash_token(token: str) -> str:
    """Create a short hash of token for safe logging."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


class DeviceRepository:
    """Repository for device operations.
    
    Handles device registration, updates, and queries for push notification
    token management.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, device_id: UUID) -> Device | None:
        """Get device by ID.
        
        Args:
            device_id: Device UUID
        
        Returns:
            Device if found, None otherwise
        """
        result = await self.session.execute(
            select(Device).where(Device.id == device_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(
        self,
        user_id: UUID,
        active_only: bool = True,
    ) -> list[Device]:
        """Get all devices for a user.
        
        Args:
            user_id: User UUID
            active_only: If True, only return active devices
        
        Returns:
            List of devices for the user
        """
        query = select(Device).where(Device.user_id == user_id)
        
        if active_only:
            query = query.where(Device.is_active == True)  # noqa: E712
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_token(
        self,
        user_id: UUID,
        notification_token: str,
    ) -> Device | None:
        """Get device by user and notification token.
        
        Args:
            user_id: User UUID
            notification_token: OneSignal player_id
        
        Returns:
            Device if found, None otherwise
        """
        result = await self.session.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.notification_token == notification_token,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: UUID,
        platform: str,
        notification_token: str,
        device_name: str | None = None,
    ) -> Device:
        """Create or update a device registration.
        
        Uses PostgreSQL upsert (INSERT ... ON CONFLICT) to atomically
        create or update a device. If a device with the same user_id and
        notification_token exists, updates it. Otherwise creates a new one.
        
        Args:
            user_id: User UUID (can be guest)
            platform: Device platform ("ios", "android", "web")
            notification_token: OneSignal player_id / subscription_id
            device_name: Optional human-readable device name
        
        Returns:
            The created or updated Device
        """
        token_hash = _hash_token(notification_token)
        
        # PostgreSQL upsert using INSERT ... ON CONFLICT
        stmt = insert(Device).values(
            user_id=user_id,
            platform=platform,
            notification_token=notification_token,
            device_name=device_name,
            is_active=True,
        )
        
        # On conflict (same user + token), update fields
        stmt = stmt.on_conflict_do_update(
            constraint="uq_devices_user_id_notification_token",
            set_={
                "platform": stmt.excluded.platform,
                "device_name": stmt.excluded.device_name,
                "is_active": True,  # Re-activate if previously deactivated
                "updated_at": stmt.excluded.updated_at,
            },
        ).returning(Device)
        
        result = await self.session.execute(stmt)
        device = result.scalar_one()
        
        logger.info(
            "device_upserted",
            device_id=str(device.id),
            user_id=str(user_id),
            platform=platform,
            token_hash=token_hash,
        )
        
        return device

    async def deactivate(self, device_id: UUID) -> bool:
        """Deactivate a device (mark as inactive).
        
        Called when a notification token is found to be invalid or the device
        has unsubscribed from notifications.
        
        Args:
            device_id: Device UUID to deactivate
        
        Returns:
            True if device was deactivated, False if not found
        """
        result = await self.session.execute(
            update(Device)
            .where(Device.id == device_id)
            .values(is_active=False)
            .returning(Device.id)
        )
        
        deactivated = result.scalar_one_or_none()
        
        if deactivated:
            logger.info("device_deactivated", device_id=str(device_id))
            return True
        
        return False

    async def deactivate_by_token(
        self,
        notification_token: str,
    ) -> int:
        """Deactivate all devices with a given token.
        
        Used when OneSignal reports a player_id as invalid, which may
        affect devices across multiple users (rare but possible).
        
        Args:
            notification_token: The invalid OneSignal player_id
        
        Returns:
            Number of devices deactivated
        """
        token_hash = _hash_token(notification_token)
        
        result = await self.session.execute(
            update(Device)
            .where(
                Device.notification_token == notification_token,
                Device.is_active == True,  # noqa: E712
            )
            .values(is_active=False)
            .returning(Device.id)
        )
        
        count = len(result.fetchall())
        
        if count > 0:
            logger.info(
                "devices_deactivated_by_token",
                token_hash=token_hash,
                count=count,
            )
        
        return count

    async def delete(self, device_id: UUID) -> bool:
        """Delete a device.
        
        Args:
            device_id: Device UUID to delete
        
        Returns:
            True if device was deleted, False if not found
        """
        device = await self.get_by_id(device_id)
        
        if device:
            await self.session.delete(device)
            logger.info("device_deleted", device_id=str(device_id))
            return True
        
        return False
