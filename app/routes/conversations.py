"""Conversation endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.core.errors import ConversationNotFoundError
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.events import ConversationResponse
from app.services.conversations_service import ConversationsService

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    """Create a new conversation for the authenticated user."""
    service = ConversationsService(session)
    return await service.create_conversation(current_user.id)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    """Get a conversation by ID."""
    service = ConversationsService(session)
    conversation = await service.get_conversation(conversation_id, current_user.id)
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    return conversation
