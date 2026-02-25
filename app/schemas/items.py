"""Item schemas."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import ItemEventType, ItemPriority, ItemStatus, ItemType


class ItemResponse(BaseModel):
    """Schema for item response."""

    id: UUID
    conversation_id: UUID
    type: ItemType
    title: str
    content: str | None
    due_at: datetime | None
    timezone: str | None
    priority: ItemPriority
    category: str
    status: ItemStatus
    pinned: bool
    tags: list[str] | None
    source_message_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


class ItemEventResponse(BaseModel):
    """Schema for item event response."""

    id: UUID
    item_id: UUID
    conversation_id: UUID
    proposal_id: UUID | None
    event_type: ItemEventType
    before: dict | None
    after: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# Query params for list items endpoint
ItemListStatus = Literal["all", "active", "done", "canceled", "archived"]
ItemListType = Literal["all", "task", "note"]


class ItemCreateRequest(BaseModel):
    """Schema for creating an item directly (not via proposal)."""

    type: ItemType
    title: str = Field(min_length=1, max_length=500)
    content: str | None = None
    due_at: datetime | None = None
    timezone: str | None = None
    priority: ItemPriority = ItemPriority.MEDIUM
    category: str = "GENERAL"
    pinned: bool = False
    tags: list[str] | None = None


class ItemUpdateRequest(BaseModel):
    """Schema for updating an item directly (not via proposal)."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = None
    due_at: datetime | None = None
    timezone: str | None = None
    priority: ItemPriority | None = None
    category: str | None = None
    status: ItemStatus | None = None
    pinned: bool | None = None
    tags: list[str] | None = None
