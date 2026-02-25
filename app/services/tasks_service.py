"""Tasks service - Legacy compatibility layer.

This module provides backward compatibility by wrapping ItemsService
with Task-specific filtering. New code should use ItemsService directly.
"""

from datetime import date
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.item_repo import ItemRepository
from app.schemas.enums import ItemPriority, ItemStatus, ItemType
from app.schemas.items import ItemResponse
from app.schemas.tasks import TaskResponse

logger = structlog.get_logger(__name__)


class TasksService:
    """
    Legacy service for task operations.
    
    Wraps ItemRepository with type=TASK filtering.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ItemRepository(session)

    async def list_tasks(
        self,
        conversation_id: UUID,
        user_id: UUID,
        status: ItemStatus | None = None,
    ) -> list[TaskResponse]:
        """List tasks for a conversation."""
        status_value = status.value if status else None
        items = await self.repo.list_conversation_items(
            conversation_id,
            user_id=user_id,
            status_filter=status_value,
            type_filter="TASK",
        )
        return [
            TaskResponse(
                id=item.id,
                conversation_id=item.conversation_id,
                title=item.title,
                description=item.content,
                due_at=item.due_at,
                timezone=item.timezone,
                priority=ItemPriority(item.priority),
                category=item.category if item.category != "GENERAL" else None,
                status=ItemStatus(item.status),
                source_message_id=item.source_message_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
                deleted_at=item.deleted_at,
            )
            for item in items
        ]

    async def get_task(self, task_id: UUID, user_id: UUID) -> TaskResponse | None:
        """Get a single task with ownership check."""
        item = await self.repo.get_by_id_and_user(task_id, user_id)
        if not item or item.type != "TASK":
            return None
        return TaskResponse(
            id=item.id,
            conversation_id=item.conversation_id,
            title=item.title,
            description=item.content,
            due_at=item.due_at,
            timezone=item.timezone,
            priority=ItemPriority(item.priority),
            category=item.category if item.category != "GENERAL" else None,
            status=ItemStatus(item.status),
            source_message_id=item.source_message_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            deleted_at=item.deleted_at,
        )

    async def list_user_tasks(
        self,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        status_filter: str | None = None,
    ) -> list[TaskResponse]:
        """
        List all tasks for a user across all conversations.
        
        Args:
            user_id: The user's ID
            date_from: Filter by due_at >= start of date
            date_to: Filter by due_at < start of next date
            status_filter: "active", "cancelled", "done", or "all"
        
        Returns:
            List of TaskResponse objects
        """
        # Map legacy status values to new ones
        status_map = {
            "active": "ACTIVE",
            "cancelled": "CANCELED",
            "done": "DONE",
            "all": None,
        }
        status_for_repo = status_map.get(status_filter) if status_filter else None
        
        items = await self.repo.list_user_items(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            status_filter=status_for_repo,
            type_filter="TASK",
        )
        
        return [
            TaskResponse(
                id=item.id,
                conversation_id=item.conversation_id,
                title=item.title,
                description=item.content,
                due_at=item.due_at,
                timezone=item.timezone,
                priority=ItemPriority(item.priority),
                category=item.category if item.category != "GENERAL" else None,
                status=ItemStatus(item.status),
                source_message_id=item.source_message_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
                deleted_at=item.deleted_at,
            )
            for item in items
        ]

    async def mark_task_as_complete(self, task_id: UUID, user_id: UUID) -> ItemResponse | None:
        """Mark a task as complete."""
        item = await self.repo.get_by_id_and_user(task_id, user_id)
        if not item or item.type != "TASK":
            return None
        
        updated_item = await self.repo.mark_as_complete(item.id)
        
        return ItemResponse(
            id=updated_item.id,
            conversation_id=updated_item.conversation_id,
            title=updated_item.title,
            content=updated_item.content,
            due_at=updated_item.due_at,
            timezone=updated_item.timezone,
            priority=ItemPriority(updated_item.priority),
            category=updated_item.category,
            status=ItemStatus(updated_item.status),
            source_message_id=updated_item.source_message_id,
            type=ItemType(updated_item.type),
            pinned=updated_item.pinned,
            tags=updated_item.tags,
            created_at=updated_item.created_at,
            updated_at=updated_item.updated_at,
            deleted_at=updated_item.deleted_at,
        )