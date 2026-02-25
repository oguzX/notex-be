"""Authentication service."""

from datetime import datetime, timedelta
from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_token
from app.core.config import get_settings
from app.db.repositories.refresh_token_repo import RefreshTokenRepository
from app.db.repositories.user_repo import UserRepository
from app.schemas.auth import TokenResponse
from app.utils.ids import generate_refresh_token

logger = structlog.get_logger(__name__)


class AuthService:
    """Service for authentication operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.token_repo = RefreshTokenRepository(session)
        self.settings = get_settings()

    async def register_guest(self, client_uuid: UUID, timezone: str | None = None) -> TokenResponse:
        """
        Register or retrieve a guest user and return tokens.
        
        If a user with the given client_uuid already exists, returns tokens
        for that user. Otherwise creates a new guest user.
        """
        # Try to find existing user
        user = await self.user_repo.get_by_client_uuid(client_uuid)
        
        if not user:
            # Create new guest user
            user = await self.user_repo.create_guest(client_uuid, timezone=timezone)
            logger.info("guest_user_created", user_id=str(user.id), client_uuid=str(client_uuid))
        else:
            # Update timezone for existing user if provided
            if timezone is not None and user.timezone != timezone:
                user.timezone = timezone
                await self.session.flush()
            logger.info("guest_user_found", user_id=str(user.id), client_uuid=str(client_uuid))
        
        # Generate access token
        access_token, expires_in = create_access_token(user.id)
        
        # Generate refresh token
        refresh_token_raw = generate_refresh_token()
        refresh_token_hash = hash_token(refresh_token_raw)
        
        expires_at = datetime.utcnow() + timedelta(
            seconds=self.settings.REFRESH_TOKEN_TTL_SECONDS
        )
        
        await self.token_repo.create(
            user_id=user.id,
            token_hash=refresh_token_hash,
            expires_at=expires_at,
        )
        
        await self.session.commit()
        
        logger.info(
            "tokens_issued",
            user_id=str(user.id),
            access_token_expires_in=expires_in,
        )
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token_raw,
            token_type="bearer",
            expires_in=expires_in,
            user_id=str(user.id),
            timezone=user.timezone,
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """
        Refresh access and refresh tokens.
        
        Validates the provided refresh token, revokes it, creates a new one,
        and returns new access and refresh tokens.
        """
        token_hash = hash_token(refresh_token)
        
        # Find valid refresh token
        old_token = await self.token_repo.get_valid_by_hash(token_hash)
        
        if not old_token:
            logger.warning("invalid_refresh_token_attempt")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
        
        # Generate new tokens
        access_token, expires_in = create_access_token(old_token.user_id)
        
        new_refresh_token_raw = generate_refresh_token()
        new_refresh_token_hash = hash_token(new_refresh_token_raw)
        
        expires_at = datetime.utcnow() + timedelta(
            seconds=self.settings.REFRESH_TOKEN_TTL_SECONDS
        )
        
        # Create new refresh token
        new_token = await self.token_repo.create(
            user_id=old_token.user_id,
            token_hash=new_refresh_token_hash,
            expires_at=expires_at,
        )
        
        # Rotate old token
        await self.token_repo.rotate(old_token, new_token.id)
        
        await self.session.commit()
        
        # Load user to include timezone in response
        user = await self.user_repo.get_by_id(old_token.user_id)
        
        logger.info(
            "tokens_refreshed",
            user_id=str(old_token.user_id),
            old_token_id=str(old_token.id),
            new_token_id=str(new_token.id),
        )
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token_raw,
            token_type="bearer",
            expires_in=expires_in,
            user_id=str(old_token.user_id),
            timezone=user.timezone if user else None,
        )
