"""Context loading service for message processing."""

from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.item_repo import ItemRepository
from app.db.repositories.message_repo import MessageRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.db.repositories.user_repo import UserRepository
from app.utils.time import ensure_utc
from app.workers.message_context import MessageContext

logger = structlog.get_logger(__name__)
settings = get_settings()


class ContextLoadError(Exception):
    """Raised when context loading fails."""

    def __init__(self, message: str, field: str):
        """
        Initialize error.

        Args:
            message: Error message
            field: Field that failed to load
        """
        super().__init__(message)
        self.field = field


class ContextLoader:
    """
    Service for loading message processing context.

    Responsible for fetching all necessary data from the database
    and building a MessageContext object.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize ContextLoader.

        Args:
            session: Database session
        """
        self.session = session
        self.message_repo = MessageRepository(session)
        self.conversation_repo = ConversationRepository(session)
        self.proposal_repo = ProposalRepository(session)
        self.user_repo = UserRepository(session)
        self.item_repo = ItemRepository(session)

    async def load_context(
        self,
        conversation_id: UUID,
        message_id: UUID,
        version: int,
        auto_apply: bool,
        timezone: str,
    ) -> MessageContext:
        """
        Load all context data for message processing.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            version: Conversation version
            auto_apply: Whether to auto-apply proposals
            timezone: User-provided timezone

        Returns:
            MessageContext with all loaded data

        Raises:
            ContextLoadError: If any required data cannot be loaded
        """
        logger.info(
            "loading_context",
            conversation_id=str(conversation_id),
            message_id=str(message_id),
            version=version,
        )

        # Load message
        message = await self.message_repo.get_by_id(message_id)
        if not message:
            raise ContextLoadError("Message not found", "message")

        # Load conversation
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        if not conversation:
            raise ContextLoadError("Conversation not found", "conversation")

        # Load proposal
        proposal = await self._load_proposal(conversation_id, message_id, version)
        if not proposal:
            raise ContextLoadError("Proposal not found", "proposal")

        # Load user
        user = await self.user_repo.get_by_id(conversation.user_id)

        # Compute reference time (message creation time in UTC)
        reference_dt_utc = ensure_utc(message.created_at)

        # Determine final timezone (user preference > client-provided > UTC)
        final_timezone = timezone
        if user and user.timezone:
            final_timezone = user.timezone
            logger.info(
                "using_user_timezone",
                user_id=str(conversation.user_id),
                timezone=final_timezone,
            )

        logger.info(
            "context_loaded",
            message_id=str(message_id),
            reference_dt_utc=reference_dt_utc.isoformat(),
            timezone=final_timezone,
        )

        return MessageContext(
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
            auto_apply=auto_apply,
            timezone=final_timezone,
            message=message,
            conversation=conversation,
            proposal=proposal,
            user=user,
            reference_dt_utc=reference_dt_utc,
        )

    async def _load_proposal(
        self,
        conversation_id: UUID,
        message_id: UUID,
        version: int,
    ) -> Any:
        """
        Load proposal matching message and version.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            version: Conversation version

        Returns:
            Proposal if found, None otherwise
        """
        proposals = await self.proposal_repo.list_by_conversation(
            conversation_id,
            limit=100,
        )

        for proposal in proposals:
            if proposal.message_id == message_id and proposal.version == version:
                return proposal

        return None

    async def load_messages_context(
        self,
        conversation_id: UUID,
    ) -> list[dict[str, str]]:
        """
        Load recent messages for LLM context.

        Args:
            conversation_id: Conversation ID

        Returns:
            List of message dictionaries with role and content
        """
        messages = await self.message_repo.get_recent_context(
            conversation_id,
            limit=settings.CONTEXT_MESSAGE_LIMIT,
        )

        return [
            {
                "role": msg.role,
                "content": msg.content,
            }
            for msg in messages
        ]

    async def load_items_snapshot(
        self,
        conversation_id: UUID,
        timezone: str = "UTC",
    ) -> list[dict[str, Any]]:
        """
        Load active items snapshot.

        Converts due_at from UTC to user-local timezone so the LLM sees
        times in the same timezone it is told to output in.

        Args:
            conversation_id: Conversation ID
            timezone: User timezone for display

        Returns:
            List of item dictionaries with localized times
        """
        try:
            tz = ZoneInfo(timezone)
        except Exception:
            tz = ZoneInfo("UTC")
            logger.warning("invalid_timezone", timezone=timezone, fallback="UTC")

        items = await self.item_repo.get_active_snapshot(conversation_id)

        return [
            {
                "id": str(item.id),
                "type": item.type,
                "title": item.title,
                "content": item.content,
                "due_at": item.due_at.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")
                if item.due_at
                else None,
                "priority": item.priority,
                "status": item.status,
                "pinned": item.pinned,
                "tags": item.tags,
            }
            for item in items
        ]
