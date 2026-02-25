"""Message repository."""

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.message import Message


class MessageRepository:
    """Repository for message database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_client_message_id(
        self,
        conversation_id: UUID,
        client_message_id: str,
    ) -> Message | None:
        """Get message by conversation_id and client_message_id for idempotency.

        This is used to check if a message with the same client_message_id
        already exists for a conversation, enabling idempotent message creation.

        Args:
            conversation_id: The conversation UUID.
            client_message_id: The client-provided idempotency key.

        Returns:
            The existing message if found, None otherwise.
        """
        result = await self.session.execute(
            select(Message).where(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.client_message_id == client_message_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        client_message_id: str | None = None,
    ) -> Message:
        """Create a new message."""
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            client_message_id=client_message_id,
        )
        self.session.add(message)
        await self.session.flush()
        await self.session.refresh(message)
        return message

    async def get_by_id(self, message_id: UUID) -> Message | None:
        """Get message by ID."""
        result = await self.session.execute(
            select(Message).where(Message.id == message_id)
        )
        return result.scalar_one_or_none()

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int | None = None,
    ) -> list[Message]:
        """List messages for a conversation, ordered by creation time."""
        query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await self.session.execute(query)
        messages = list(result.scalars().all())
        return list(reversed(messages))  # Return in chronological order

    async def get_recent_context(
        self,
        conversation_id: UUID,
        limit: int = 20,
    ) -> list[Message]:
        """Get recent messages for context."""
        return await self.list_by_conversation(conversation_id, limit=limit)
