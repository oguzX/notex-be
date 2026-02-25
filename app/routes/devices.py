"""Device registration endpoints for push notifications."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.db.repositories.device_repo import DeviceRepository
from app.db.session import get_session
from app.schemas.devices import (
    DeviceListResponse,
    DeviceRegisterRequest,
    DeviceResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/devices", status_code=status.HTTP_201_CREATED)
async def register_device(
    request: DeviceRegisterRequest,
    user_id: UUID = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceResponse:
    """Register or update a device for push notifications.
    
    Registers a new device or updates an existing one with the same
    notification_token for the authenticated user.
    
    The notification_token is the OneSignal player_id (subscription ID).
    If a device with the same token already exists for this user,
    it will be updated (and re-activated if previously deactivated).
    
    This endpoint supports guest users - device registration does not
    require a registered account.
    
    Args:
        request: Device registration data
        user_id: Authenticated user ID (from JWT)
        session: Database session
    
    Returns:
        DeviceResponse with device details (excluding token)
    """
    repo = DeviceRepository(session)
    
    device = await repo.upsert(
        user_id=user_id,
        platform=request.platform,
        notification_token=request.notification_token,
        device_name=request.device_name,
    )
    
    await session.commit()
    
    logger.info(
        "device_registered",
        user_id=str(user_id),
        device_id=str(device.id),
        platform=request.platform,
    )
    
    return DeviceResponse.model_validate(device)


@router.get("/devices", status_code=status.HTTP_200_OK)
async def list_devices(
    user_id: UUID = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceListResponse:
    """List all registered devices for the authenticated user.
    
    Returns all devices (both active and inactive) registered for
    the current user.
    
    Args:
        user_id: Authenticated user ID
        session: Database session
    
    Returns:
        DeviceListResponse with list of devices
    """
    repo = DeviceRepository(session)
    
    # Get all devices including inactive
    devices = await repo.get_by_user_id(user_id, active_only=False)
    
    return DeviceListResponse(
        devices=[DeviceResponse.model_validate(d) for d in devices],
        count=len(devices),
    )


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    user_id: UUID = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a device registration.
    
    Removes the device from push notification delivery. The device
    must belong to the authenticated user.
    
    Args:
        device_id: Device UUID to delete
        user_id: Authenticated user ID
        session: Database session
    
    Returns:
        No content on success
    
    Raises:
        404: If device not found or doesn't belong to user
    """
    from fastapi import HTTPException
    
    repo = DeviceRepository(session)
    
    # Check device exists and belongs to user
    device = await repo.get_by_id(device_id)
    
    if not device or device.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    
    await repo.delete(device_id)
    await session.commit()
    
    logger.info(
        "device_deleted_by_user",
        user_id=str(user_id),
        device_id=str(device_id),
    )
