"""Items service."""

from datetime import date
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.item_repo import ItemRepository
from app.schemas.enums import ItemStatus, ItemType
from app.schemas.items import ItemResponse

logger = structlog.get_logger(__name__)


class ItemsService:
    """Service for item operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ItemRepository(session)

    async def list_items(
        self,
        conversation_id: UUID,
        user_id: UUID,
        status: ItemStatus | None = None,
        item_type: ItemType | None = None,
    ) -> list[ItemResponse]:
        """List items for a conversation."""
        status_value = status.value if status else None
        type_value = item_type.value if item_type else None
        items = await self.repo.list_conversation_items(
            conversation_id,
            user_id=user_id,
            status_filter=status_value,
            type_filter=type_value,
        )
        return [ItemResponse.model_validate(i) for i in items]

    async def get_item(self, item_id: UUID, user_id: UUID) -> ItemResponse | None:
        """Get a single item with ownership check."""
        item = await self.repo.get_by_id_and_user(item_id, user_id)
        if not item:
            return None
        return ItemResponse.model_validate(item)

    async def list_user_items(
        self,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        status_filter: str | None = None,
        type_filter: str | None = None,
    ) -> list[ItemResponse]:
        """
        List all items for a user across all conversations.
        
        Args:
            user_id: The user's ID
            date_from: Filter by due_at >= start of date (for tasks)
            date_to: Filter by due_at < start of next date (for tasks)
            status_filter: "ACTIVE", "DONE", "CANCELED", "ARCHIVED", or "all"
            type_filter: "TASK", "NOTE", or "all"
        
        Returns:
            List of ItemResponse objects
        """
        # Convert "all" to None for repo
        status_for_repo = None if status_filter in ["all", None] else status_filter
        type_for_repo = None if type_filter in ["all", None] else type_filter
        
        items = await self.repo.list_user_items(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            status_filter=status_for_repo,
            type_filter=type_for_repo,
        )
        
        return [ItemResponse.model_validate(i) for i in items]

    async def get_items_snapshot(
        self,
        conversation_id: UUID,
        item_type: str | None = None,
    ) -> list[dict]:
        """
        Get a snapshot of active items for LLM context.
        
        Returns a list of dicts suitable for JSON serialization.
        """
        items = await self.repo.get_active_snapshot(conversation_id, item_type)
        return [
            {
                "id": str(item.id),
                "type": item.type,
                "title": item.title,
                "content": item.content,
                "due_at": item.due_at.isoformat() if item.due_at else None,
                "priority": item.priority,
                "category": item.category,
                "status": item.status,
                "pinned": item.pinned,
                "tags": item.tags,
            }
            for item in items
        ]
