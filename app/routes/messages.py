"""Message endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.db.models.user import User
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.session import get_session
from app.schemas.messages import (
    MessageCreate,
    MessageEnqueuedResponse,
    MessageResponse,
)
from app.services.messages_service import MessagesService

router = APIRouter()


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MessageEnqueuedResponse:
    """
    Create a user message and enqueue it for LLM processing.

    The message text is stored as-is and sent through the worker
    pipeline where the LLM classifies the user's intent (approve,
    cancel, note-only, or standard ops) and dispatches accordingly.
    The endpoint itself never interprets the text.
    """
    # Verify conversation ownership
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_id_and_user(
        conversation_id, current_user.id
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation not found or access denied",
        )

    service = MessagesService(session)
    return await service.create_message(conversation_id, data)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    """List all messages for a conversation."""
    # Verify conversation ownership
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_id_and_user(
        conversation_id, current_user.id
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation not found or access denied",
        )
    
    service = MessagesService(session)
    return await service.list_messages(conversation_id)
