"""Refresh token repository."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    """Repository for refresh token operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        """Create a new refresh token."""
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_valid_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Get valid refresh token by hash (not revoked and not expired)."""
        now = datetime.utcnow()
        result = await self.session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .where(RefreshToken.revoked_at.is_(None))
            .where(RefreshToken.expires_at > now)
        )
        return result.scalar_one_or_none()

    async def rotate(self, old_token: RefreshToken, new_token_id: UUID) -> None:
        """Rotate refresh token by revoking the old one."""
        old_token.revoked_at = datetime.utcnow()
        old_token.replaced_by_token_id = new_token_id
        await self.session.flush()

    async def revoke(self, token_id: UUID) -> None:
        """Revoke a refresh token."""
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.id == token_id)
        )
        token = result.scalar_one_or_none()
        if token:
            token.revoked_at = datetime.utcnow()
            await self.session.flush()
