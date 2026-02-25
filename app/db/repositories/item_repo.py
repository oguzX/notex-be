"""Item repository."""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, nulls_last, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.item import Item


class ItemRepository:
    """Repository for item database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        conversation_id: UUID,
        user_id: UUID,
        item_type: str,
        title: str,
        content: str | None = None,
        due_at: datetime | None = None,
        timezone: str | None = None,
        priority: str = "MEDIUM",
        category: str = "GENERAL",
        status: str = "ACTIVE",
        pinned: bool = False,
        tags: list[str] | None = None,
        source_message_id: UUID | None = None,
    ) -> Item:
        """Create a new item."""
        item = Item(
            conversation_id=conversation_id,
            user_id=user_id,
            type=item_type,
            title=title,
            content=content,
            due_at=due_at,
            timezone=timezone,
            priority=priority,
            category=category,
            status=status,
            pinned=pinned,
            tags=tags,
            source_message_id=source_message_id,
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def get_by_id(self, item_id: UUID) -> Item | None:
        """Get item by ID."""
        result = await self.session.execute(select(Item).where(Item.id == item_id))
        return result.scalar_one_or_none()

    async def get_by_id_and_user(self, item_id: UUID, user_id: UUID) -> Item | None:
        """Get item by ID with user ownership check."""
        result = await self.session.execute(
            select(Item).where(
                and_(
                    Item.id == item_id,
                    Item.user_id == user_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        item_id: UUID,
        **fields: Any,
    ) -> Item:
        """Update item fields safely with commit."""
        # 1. Veriyi çek
        item = await self.get_by_id(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        
        # 2. Field'ları güncelle (Dynamic Attribute Setting)
        for key, value in fields.items():
            if hasattr(item, key):
                setattr(item, key, value)
        
        # 3. CRITICAL FIX: Flush yerine Commit kullanılmalı.
        # Commit, transaction'ı tamamlar ve veriyi kalıcı olarak DB'ye yazar.
        try:
            await self.session.commit()
            await self.session.refresh(item) # DB'den güncel halini (örneğin auto-update alanları) geri çek
        except Exception as e:
            await self.session.rollback() # Hata durumunda session'ı temizle
            raise e

        return item

    async def soft_delete(self, item_id: UUID) -> Item:
        """Soft delete an item."""
        return await self.update(
            item_id,
            deleted_at=datetime.now(),
            status="CANCELED",
        )

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        status: str | None = None,
        item_type: str | None = None,
        include_deleted: bool = False,
    ) -> list[Item]:
        """List items for a conversation."""
        conditions = [Item.conversation_id == conversation_id]
        
        if not include_deleted:
            conditions.append(Item.deleted_at.is_(None))
        
        if status:
            conditions.append(Item.status == status)
        
        if item_type:
            conditions.append(Item.type == item_type)
        
        result = await self.session.execute(
            select(Item)
            .where(and_(*conditions))
            .order_by(Item.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_snapshot(
        self,
        conversation_id: UUID,
        item_type: str | None = None,
    ) -> list[Item]:
        """Get snapshot of active items for context."""
        return await self.list_by_conversation(
            conversation_id,
            status="ACTIVE",
            item_type=item_type,
            include_deleted=False,
        )

    async def search_by_time_window(
        self,
        conversation_id: UUID,
        target_time: datetime,
        window_minutes: int = 45,
    ) -> list[Item]:
        """Search items by time window (tasks only)."""
        start = target_time - timedelta(minutes=window_minutes)
        end = target_time + timedelta(minutes=window_minutes)
        
        result = await self.session.execute(
            select(Item).where(
                and_(
                    Item.conversation_id == conversation_id,
                    Item.deleted_at.is_(None),
                    Item.type == "TASK",
                    Item.due_at.between(start, end),
                )
            )
        )
        return list(result.scalars().all())

    async def get_items_in_window(
        self,
        user_id: UUID,
        window_start: datetime,
        window_end: datetime,
        exclude_statuses: list[str] | None = None,
        limit: int = 10,
    ) -> list[Item]:
        """
        Get task items for a user within a time window.
        
        Args:
            user_id: The user's ID
            window_start: Start of the time window
            window_end: End of the time window
            exclude_statuses: List of statuses to exclude (default: ["CANCELED"])
            limit: Maximum number of items to return
        
        Returns:
            List of items ordered by due_at asc
        """
        if exclude_statuses is None:
            exclude_statuses = ["CANCELED"]
        
        conditions = [
            Item.user_id == user_id,
            Item.deleted_at.is_(None),
            Item.type == "TASK",
            Item.due_at.isnot(None),
            Item.due_at >= window_start,
            Item.due_at <= window_end,
        ]
        
        if exclude_statuses:
            conditions.append(~Item.status.in_(exclude_statuses))
        
        result = await self.session.execute(
            select(Item)
            .where(and_(*conditions))
            .order_by(Item.due_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_conflicting_items(
        self,
        user_id: UUID,
        target_time: datetime,
        window_minutes: int = 30,
        exclude_item_ids: list[UUID] | None = None,
    ) -> list[Item]:
        """
        Find task items that conflict with a target time.
        
        Args:
            user_id: The user's ID
            target_time: The proposed time for the new task
            window_minutes: Conflict window in minutes (±)
            exclude_item_ids: Item IDs to exclude from conflict detection
        
        Returns:
            List of conflicting active task items
        """
        window_start = target_time - timedelta(minutes=window_minutes)
        window_end = target_time + timedelta(minutes=window_minutes)
        
        conditions = [
            Item.user_id == user_id,
            Item.deleted_at.is_(None),
            Item.type == "TASK",
            Item.status == "ACTIVE",
            Item.due_at.isnot(None),
            Item.due_at >= window_start,
            Item.due_at <= window_end,
        ]
        
        if exclude_item_ids:
            conditions.append(~Item.id.in_(exclude_item_ids))
        
        result = await self.session.execute(
            select(Item)
            .where(and_(*conditions))
            .order_by(Item.due_at.asc())
        )
        return list(result.scalars().all())

    async def list_user_items(
        self,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        status_filter: str | None = None,
        type_filter: str | None = None,
    ) -> list[Item]:
        """
        List all items belonging to a user.
        
        Args:
            user_id: The user's ID
            date_from: Filter tasks with due_at >= start of this date (UTC)
            date_to: Filter tasks with due_at < start of (date_to + 1 day) (UTC)
            status_filter: "ACTIVE", "DONE", "CANCELED", "ARCHIVED" or None for all
            type_filter: "TASK", "NOTE" or None for all
        
        Returns:
            List of items with combined sorting:
            - Tasks with due_at first (sorted by due_at asc)
            - Then notes (pinned first, then by updated_at desc)
        """
        conditions = [
            Item.user_id == user_id,
            Item.deleted_at.is_(None),
        ]
        
        # Apply status filter
        if status_filter:
            conditions.append(Item.status == status_filter)
        
        # Apply type filter
        if type_filter:
            conditions.append(Item.type == type_filter)
        
        # Date filters apply only to TASK items
        date_conditions = []
        if date_from:
            date_from_dt = datetime.combine(date_from, datetime.min.time())
            date_conditions.append(
                or_(
                    Item.type != "TASK",
                    Item.due_at >= date_from_dt,
                )
            )
        
        if date_to:
            date_to_dt = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
            date_conditions.append(
                or_(
                    Item.type != "TASK",
                    Item.due_at < date_to_dt,
                )
            )
        
        if date_conditions:
            conditions.extend(date_conditions)
        
        # Combined sorting:
        # 1. Tasks with due_at come first (sorted by due_at asc)
        # 2. Notes come next (pinned first, then updated_at desc)
        # 3. Tasks without due_at at the end
        result = await self.session.execute(
            select(Item)
            .where(and_(*conditions))
            .order_by(
                # Tasks with due_at first
                case(
                    (and_(Item.type == "TASK", Item.due_at.isnot(None)), 0),
                    (Item.type == "NOTE", 1),
                    else_=2
                ),
                # Secondary sort: due_at for tasks, pinned desc for notes
                nulls_last(Item.due_at.asc()),
                Item.pinned.desc(),
                Item.updated_at.desc(),
            )
        )
        return list(result.scalars().all())

    async def list_conversation_items(
        self,
        conversation_id: UUID,
        user_id: UUID,
        status_filter: str | None = None,
        type_filter: str | None = None,
    ) -> list[Item]:
        """
        List items for a specific conversation owned by user.
        
        Args:
            conversation_id: The conversation's ID
            user_id: The user's ID (for ownership verification)
            status_filter: Optional status filter
            type_filter: Optional type filter
        
        Returns:
            List of items
        """
        conditions = [
            Item.conversation_id == conversation_id,
            Item.user_id == user_id,
            Item.deleted_at.is_(None),
        ]
        
        if status_filter:
            conditions.append(Item.status == status_filter)
        
        if type_filter:
            conditions.append(Item.type == type_filter)
        
        result = await self.session.execute(
            select(Item)
            .where(and_(*conditions))
            .order_by(
                nulls_last(Item.due_at.asc()),
                Item.pinned.desc(),
                Item.updated_at.desc(),
            )
        )
        return list(result.scalars().all())
    
    async def mark_as_complete(self, item_id: UUID) -> Item:
        """Mark an item as complete."""
        return await self.update(
            item_id,
            status="DONE",
            completed_at=datetime.now(),
        )

    async def toggle_complete(self, item_id: UUID) -> Item:
        """Toggle an item's completion status."""
        item = await self.get_by_id(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        
        if item.status == "DONE":
            # Mark as active
            return await self.update(
                item_id,
                status="ACTIVE",
                completed_at=None,
            )
        else:
            # Mark as done
            return await self.update(
                item_id,
                status="DONE",
                completed_at=datetime.now(),
            )