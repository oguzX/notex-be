"""Messages service."""

from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.message_repo import MessageRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.events.bus import get_event_bus
from app.schemas.enums import EventType, MessageRole
from app.schemas.events import WsEvent
from app.schemas.messages import MessageCreate, MessageEnqueuedResponse, MessageResponse
from app.workers.celery_app import get_celery_app

logger = structlog.get_logger(__name__)


class MessagesService:
    """Service for message operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.message_repo = MessageRepository(session)
        self.conversation_repo = ConversationRepository(session)
        self.proposal_repo = ProposalRepository(session)

    async def create_message(
        self,
        conversation_id: UUID,
        data: MessageCreate,
    ) -> MessageEnqueuedResponse:
        """Create a message and enqueue processing.

        This is the core entry point for user messages.

        If client_message_id is provided, this method is idempotent:
        - If a message with the same (conversation_id, client_message_id) exists,
          returns the existing message without creating a new one or enqueuing work.
        - This prevents duplicate processing from accidental retries.
        """
        # Idempotency check: if client_message_id provided, check for existing
        if data.client_message_id:
            existing = await self.message_repo.get_by_client_message_id(
                conversation_id, data.client_message_id
            )
            if existing:
                # Return existing message data without re-enqueueing
                # Get the current version (not incrementing)
                current_version = await self.conversation_repo.get_version(
                    conversation_id
                )
                logger.info(
                    "idempotent_message_returned",
                    conversation_id=str(conversation_id),
                    message_id=str(existing.id),
                    client_message_id=data.client_message_id,
                )
                return MessageEnqueuedResponse(
                    message_id=existing.id,
                    conversation_id=conversation_id,
                    version=current_version,
                    enqueued=False,  # Indicate this was not newly enqueued
                )

        # Increment conversation version atomically
        version = await self.conversation_repo.increment_version(conversation_id)

        # Store message
        message = await self.message_repo.create(
            conversation_id=conversation_id,
            role=MessageRole.USER.value,
            content=data.content,
            client_message_id=data.client_message_id,
        )

        # Create proposal record
        proposal = await self.proposal_repo.create(
            conversation_id=conversation_id,
            message_id=message.id,
            version=version,
            status="queued",
        )

        await self.session.commit()

        logger.info(
            "message_created",
            conversation_id=str(conversation_id),
            message_id=str(message.id),
            version=version,
        )

        # Publish message received event
        event_bus = get_event_bus()
        await event_bus.publish(
            WsEvent(
                type=EventType.MESSAGE_RECEIVED,
                conversation_id=conversation_id,
                message_id=message.id,
                version=version,
            )
        )

        # Enqueue Celery task for LLM processing
        celery_app = get_celery_app()
        celery_app.send_task(
            "app.workers.tasks.process_message",
            args=[
                str(conversation_id),
                str(message.id),
                version,
                data.auto_apply,
                data.timezone,
            ],
        )

        # Publish queued event
        await event_bus.publish(
            WsEvent(
                type=EventType.LLM_QUEUED,
                conversation_id=conversation_id,
                message_id=message.id,
                proposal_id=proposal.id,
                version=version,
            )
        )

        logger.info(
            "message_enqueued",
            conversation_id=str(conversation_id),
            message_id=str(message.id),
            proposal_id=str(proposal.id),
            version=version,
        )

        return MessageEnqueuedResponse(
            message_id=message.id,
            conversation_id=conversation_id,
            version=version,
        )

    async def list_messages(self, conversation_id: UUID) -> list[MessageResponse]:
        """List all messages for a conversation."""
        messages = await self.message_repo.list_by_conversation(conversation_id)
        return [MessageResponse.model_validate(m) for m in messages]
