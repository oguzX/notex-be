"""Item event repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.item_event import ItemEvent


class ItemEventRepository:
    """Repository for item event database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        item_id: UUID,
        conversation_id: UUID,
        event_type: str,
        before: dict | None = None,
        after: dict | None = None,
        proposal_id: UUID | None = None,
    ) -> ItemEvent:
        """Create a new item event."""
        event = ItemEvent(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type=event_type,
            before=before,
            after=after,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def list_by_item(
        self,
        item_id: UUID,
        limit: int | None = None,
    ) -> list[ItemEvent]:
        """List events for an item."""
        query = (
            select(ItemEvent)
            .where(ItemEvent.item_id == item_id)
            .order_by(ItemEvent.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int | None = None,
    ) -> list[ItemEvent]:
        """List events for a conversation."""
        query = (
            select(ItemEvent)
            .where(ItemEvent.conversation_id == conversation_id)
            .order_by(ItemEvent.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())
