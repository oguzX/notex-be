"""Task event repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.task_event import TaskEvent


class TaskEventRepository:
    """Repository for task event database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        task_id: UUID,
        conversation_id: UUID,
        event_type: str,
        before: dict | None = None,
        after: dict | None = None,
        proposal_id: UUID | None = None,
    ) -> TaskEvent:
        """Create a new task event."""
        event = TaskEvent(
            task_id=task_id,
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

    async def list_by_task(
        self,
        task_id: UUID,
        limit: int | None = None,
    ) -> list[TaskEvent]:
        """List events for a task."""
        query = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int | None = None,
    ) -> list[TaskEvent]:
        """List events for a conversation."""
        query = (
            select(TaskEvent)
            .where(TaskEvent.conversation_id == conversation_id)
            .order_by(TaskEvent.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())
