"""User settings endpoints (timezone, metas, options)."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.user_settings import UserUpdateRequest, UserUpdateResponse
from app.services.user_settings_service import UserSettingsService

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.patch("/user/update", status_code=status.HTTP_200_OK)
async def update_user_settings(
    request: UserUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserUpdateResponse:
    """Update user settings (timezone, metas, options).

    All fields in the request body are optional.  Only supplied fields
    are applied.  Options are deep-merged into the existing JSON.

    Returns the full current state of the user's settings after the
    update has been applied.
    """
    service = UserSettingsService(session)
    return await service.update_user(user.id, request)
