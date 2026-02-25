"""Event schemas for WebSocket and SSE."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import EventType


class MessageOpsPayload(BaseModel):
    """
    Payload containing ops for a specific message.
    
    This ensures that WebSocket events only include ops
    produced for the current message/version/proposal,
    never mixing with prior proposals or other messages.
    """

    message_id: UUID
    proposal_id: UUID
    version: int
    ops: list[dict[str, Any]]
    resolution: dict[str, Any] | None = None
    clarifications: list[dict[str, Any]] = Field(default_factory=list)
    no_op: bool = False
    tool_response: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class WsEvent(BaseModel):
    """WebSocket event schema."""

    type: EventType
    conversation_id: UUID
    message_id: UUID | None = None
    proposal_id: UUID | None = None
    version: int | None = None
    data: dict[str, Any] | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now())

    def model_dump_json(self, **kwargs: Any) -> str:
        """Override to ensure datetime serialization."""
        return super().model_dump_json(exclude_none=True, **kwargs)


class ConversationCreate(BaseModel):
    """Schema for creating a conversation."""

    user_id: UUID
    title: str | None = None


class ConversationResponse(BaseModel):
    """Schema for conversation response."""

    id: UUID
    user_id: UUID
    title: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
