"""Message schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import MessageRole


class MessageCreate(BaseModel):
    """Schema for creating a message."""

    client_message_id: str | None = None
    content: str = Field(..., min_length=1, max_length=10000)
    timezone: str = "Europe/Istanbul"
    auto_apply: bool = True


class MessageResponse(BaseModel):
    """Schema for message response."""

    id: UUID
    conversation_id: UUID
    client_message_id: str | None
    role: MessageRole
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageEnqueuedResponse(BaseModel):
    """Response after enqueueing a message for processing."""

    message_id: UUID
    conversation_id: UUID
    version: int
    enqueued: bool = True
