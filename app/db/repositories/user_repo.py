"""User repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


class UserRepository:
    """Repository for user operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_client_uuid(self, client_uuid: UUID) -> User | None:
        """Get user by client UUID."""
        result = await self.session.execute(
            select(User).where(User.client_uuid == client_uuid)
        )
        return result.scalar_one_or_none()

    async def create_guest(self, client_uuid: UUID, timezone: str | None = None) -> User:
        """Create a new guest user."""
        user = User(
            kind="GUEST",
            client_uuid=client_uuid,
            timezone=timezone,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def create(self, client_uuid: UUID, kind: str = "GUEST") -> User:
        """Create a new user."""
        user = User(
            kind=kind,
            client_uuid=client_uuid,
        )
        self.session.add(user)
        await self.session.flush()
        return user
