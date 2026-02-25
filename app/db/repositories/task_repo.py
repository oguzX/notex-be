"""Task repository."""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, nulls_last
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.task import Task
from app.db.models.task_alias import TaskAlias


class TaskRepository:
    """Repository for task database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        conversation_id: UUID,
        title: str,
        description: str | None = None,
        due_at: datetime | None = None,
        timezone: str | None = None,
        priority: str = "medium",
        category: str | None = None,
        status: str = "active",
        source_message_id: UUID | None = None,
    ) -> Task:
        """Create a new task."""
        task = Task(
            conversation_id=conversation_id,
            title=title,
            description=description,
            due_at=due_at,
            timezone=timezone,
            priority=priority,
            category=category,
            status=status,
            source_message_id=source_message_id,
        )
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def get_by_id(self, task_id: UUID) -> Task | None:
        """Get task by ID."""
        result = await self.session.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()

    async def update(
        self,
        task_id: UUID,
        **fields: Any,
    ) -> Task:
        """Update task fields."""
        task = await self.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        for key, value in fields.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def soft_delete(self, task_id: UUID) -> Task:
        """Soft delete a task."""
        return await self.update(
            task_id,
            deleted_at=datetime.now(),
            status="cancelled",
        )

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        status: str | None = None,
        include_deleted: bool = False,
    ) -> list[Task]:
        """List tasks for a conversation."""
        conditions = [Task.conversation_id == conversation_id]
        
        if not include_deleted:
            conditions.append(Task.deleted_at.is_(None))
        
        if status:
            conditions.append(Task.status == status)
        
        result = await self.session.execute(
            select(Task)
            .where(and_(*conditions))
            .order_by(Task.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_snapshot(self, conversation_id: UUID) -> list[Task]:
        """Get snapshot of active tasks for context."""
        return await self.list_by_conversation(
            conversation_id,
            status="active",
            include_deleted=False,
        )

    async def search_by_time_window(
        self,
        conversation_id: UUID,
        target_time: datetime,
        window_minutes: int = 45,
    ) -> list[Task]:
        """Search tasks by time window."""
        from datetime import timedelta
        
        start = target_time - timedelta(minutes=window_minutes)
        end = target_time + timedelta(minutes=window_minutes)
        
        result = await self.session.execute(
            select(Task).where(
                and_(
                    Task.conversation_id == conversation_id,
                    Task.deleted_at.is_(None),
                    Task.due_at.between(start, end),
                )
            )
        )
        return list(result.scalars().all())

    async def get_tasks_in_window(
        self,
        user_id: UUID,
        window_start: datetime,
        window_end: datetime,
        exclude_statuses: list[str] | None = None,
        limit: int = 10,
    ) -> list[Task]:
        """
        Get tasks for a user within a time window.
        
        Args:
            user_id: The user's ID
            window_start: Start of the time window
            window_end: End of the time window
            exclude_statuses: List of statuses to exclude (default: ["cancelled"])
            limit: Maximum number of tasks to return
        
        Returns:
            List of tasks ordered by due_at asc
        """
        if exclude_statuses is None:
            exclude_statuses = ["cancelled"]
        
        conditions = [
            Conversation.user_id == user_id,
            Task.deleted_at.is_(None),
            Task.due_at.isnot(None),
            Task.due_at >= window_start,
            Task.due_at <= window_end,
        ]
        
        if exclude_statuses:
            conditions.append(~Task.status.in_(exclude_statuses))
        
        result = await self.session.execute(
            select(Task)
            .join(Conversation, Task.conversation_id == Conversation.id)
            .where(and_(*conditions))
            .order_by(Task.due_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_conflicting_tasks(
        self,
        user_id: UUID,
        target_time: datetime,
        window_minutes: int = 30,
        exclude_task_ids: list[UUID] | None = None,
    ) -> list[Task]:
        """
        Find tasks that conflict with a target time.
        
        Args:
            user_id: The user's ID
            target_time: The proposed time for the new task
            window_minutes: Conflict window in minutes (±)
            exclude_task_ids: Task IDs to exclude from conflict detection
        
        Returns:
            List of conflicting active tasks
        """
        window_start = target_time - timedelta(minutes=window_minutes)
        window_end = target_time + timedelta(minutes=window_minutes)
        
        conditions = [
            Conversation.user_id == user_id,
            Task.deleted_at.is_(None),
            Task.status == "active",
            Task.due_at.isnot(None),
            Task.due_at >= window_start,
            Task.due_at <= window_end,
        ]
        
        if exclude_task_ids:
            conditions.append(~Task.id.in_(exclude_task_ids))
        
        result = await self.session.execute(
            select(Task)
            .join(Conversation, Task.conversation_id == Conversation.id)
            .where(and_(*conditions))
            .order_by(Task.due_at.asc())
        )
        return list(result.scalars().all())

    async def add_alias(
        self,
        task_id: UUID,
        alias: str,
        source: str = "llm_generated",
    ) -> TaskAlias:
        """Add an alias to a task."""
        task_alias = TaskAlias(task_id=task_id, alias=alias, source=source)
        self.session.add(task_alias)
        await self.session.flush()
        await self.session.refresh(task_alias)
        return task_alias

    async def list_user_tasks(
        self,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        status_filter: str | None = None,
    ) -> list[Task]:
        """
        List all tasks belonging to a user across all conversations.
        
        Args:
            user_id: The user's ID
            date_from: Filter tasks with due_at >= start of this date (UTC)
            date_to: Filter tasks with due_at < start of (date_to + 1 day) (UTC)
            status_filter: "active", "cancelled", or None for all
        
        Returns:
            List of tasks ordered by due_at asc (nulls last), created_at desc
        """
        # Join tasks -> conversations to filter by user_id
        conditions = [
            Conversation.user_id == user_id,
            Task.deleted_at.is_(None),
        ]
        
        # Apply date_from filter
        if date_from:
            # Start of date_from in UTC
            date_from_dt = datetime.combine(date_from, datetime.min.time())
            conditions.append(Task.due_at >= date_from_dt)
        
        # Apply date_to filter  
        if date_to:
            # Start of (date_to + 1 day) in UTC
            date_to_dt = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
            conditions.append(Task.due_at < date_to_dt)
        
        # Apply status filter
        if status_filter:
            if status_filter == "active":
                conditions.append(Task.status == "active")
            elif status_filter == "cancelled":
                conditions.append(Task.status == "cancelled")
            # "all" means no status filter
        
        result = await self.session.execute(
            select(Task)
            .join(Conversation, Task.conversation_id == Conversation.id)
            .where(and_(*conditions))
            .order_by(
                nulls_last(Task.due_at.asc()),
                Task.created_at.desc(),
            )
        )
        return list(result.scalars().all())

