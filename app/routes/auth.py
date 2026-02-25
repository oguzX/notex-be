"""Authentication endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.auth import GuestRegisterRequest, RefreshRequest, TokenResponse
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/register/guest", status_code=status.HTTP_201_CREATED)
async def register_guest(
    request: GuestRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """
    Register a guest user and return access and refresh tokens.
    
    If a user with the given client_uuid already exists, returns tokens
    for that existing user.
    """
    service = AuthService(session)
    return await service.register_guest(request.client_uuid, timezone=request.timezone)


@router.post("/auth/refresh", status_code=status.HTTP_200_OK)
async def refresh_tokens(
    request: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """
    Refresh access and refresh tokens.
    
    Validates the provided refresh token, revokes it, and returns
    new access and refresh tokens.
    """
    service = AuthService(session)
    return await service.refresh_tokens(request.refresh_token)
