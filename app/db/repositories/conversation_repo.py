"""Conversation repository."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation


class ConversationRepository:
    """Repository for conversation database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: UUID, title: str | None = None) -> Conversation:
        """Create a new conversation."""
        conversation = Conversation(user_id=user_id, title=title, version=0)
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        """Get conversation by ID."""
        result = await self.session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_id_and_user(
        self, conversation_id: UUID, user_id: UUID
    ) -> Conversation | None:
        """Get conversation by ID and verify user ownership."""
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def increment_version(self, conversation_id: UUID) -> int:
        """Atomically increment conversation version and return new version."""
        result = await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(version=Conversation.version + 1)
            .returning(Conversation.version)
        )
        await self.session.flush()
        new_version = result.scalar_one()
        return new_version

    async def get_version(self, conversation_id: UUID) -> int | None:
        """Get current version of conversation."""
        result = await self.session.execute(
            select(Conversation.version).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()
