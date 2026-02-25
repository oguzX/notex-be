"""Conversation service."""

from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repo import ConversationRepository
from app.schemas.events import ConversationResponse

logger = structlog.get_logger(__name__)


class ConversationsService:
    """Service for conversation operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ConversationRepository(session)

    async def create_conversation(self, user_id: UUID) -> ConversationResponse:
        """Create a new conversation for a user."""
        conversation = await self.repo.create(
            user_id=user_id,
            title=None,
        )
        await self.session.commit()
        
        logger.info(
            "conversation_created",
            conversation_id=str(conversation.id),
            user_id=str(user_id),
        )
        
        return ConversationResponse.model_validate(conversation)

    async def get_conversation(
        self, conversation_id: UUID, user_id: UUID
    ) -> ConversationResponse | None:
        """Get a conversation by ID and verify user ownership."""
        conversation = await self.repo.get_by_id_and_user(conversation_id, user_id)
        if not conversation:
            return None
        return ConversationResponse.model_validate(conversation)
