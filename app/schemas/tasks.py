"""Task schemas - Legacy compatibility layer.

This module provides backward compatibility by re-exporting Item schemas
with Task naming. New code should use app.schemas.items directly.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import ItemEventType, ItemPriority, ItemStatus, ItemType
from app.schemas.items import ItemEventResponse, ItemResponse


class TaskResponse(BaseModel):
    """
    Legacy schema for task response.
    
    Maps to ItemResponse with type=TASK. Provided for backward compatibility.
    """

    id: UUID
    conversation_id: UUID
    title: str
    description: str | None = None  # Maps to content
    due_at: datetime | None
    timezone: str | None
    priority: ItemPriority
    category: str | None
    status: ItemStatus
    source_message_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_item(cls, item: ItemResponse) -> "TaskResponse":
        """Create TaskResponse from ItemResponse."""
        return cls(
            id=item.id,
            conversation_id=item.conversation_id,
            title=item.title,
            description=item.content,
            due_at=item.due_at,
            timezone=item.timezone,
            priority=item.priority,
            category=item.category if item.category != "GENERAL" else None,
            status=item.status,
            source_message_id=item.source_message_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            deleted_at=item.deleted_at,
        )


class TaskEventResponse(BaseModel):
    """Legacy schema for task event response."""

    id: UUID
    task_id: UUID  # Maps to item_id
    conversation_id: UUID
    proposal_id: UUID | None
    event_type: ItemEventType
    before: dict | None
    after: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_item_event(cls, event: ItemEventResponse) -> "TaskEventResponse":
        """Create TaskEventResponse from ItemEventResponse."""
        return cls(
            id=event.id,
            task_id=event.item_id,
            conversation_id=event.conversation_id,
            proposal_id=event.proposal_id,
            event_type=event.event_type,
            before=event.before,
            after=event.after,
            created_at=event.created_at,
        )


# Query params enum for list all tasks
TaskListStatus = Literal["all", "active", "cancelled", "done"]

# Re-export for compatibility
TaskStatus = ItemStatus
TaskPriority = ItemPriority
TaskEventType = ItemEventType
