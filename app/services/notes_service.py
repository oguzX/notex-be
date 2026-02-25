"""Notes service."""

from datetime import datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ItemNotFoundError
from app.db.repositories.item_event_repo import ItemEventRepository
from app.db.repositories.item_repo import ItemRepository
from app.schemas.items import ItemResponse
from app.schemas.notes import ConvertNoteToTaskResponse

logger = structlog.get_logger(__name__)


class NotesService:
    """Service for note-specific operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ItemRepository(session)
        self.event_repo = ItemEventRepository(session)

    async def list_notes(
        self,
        user_id: UUID,
        status_filter: str | None = None,
    ) -> list[ItemResponse]:
        """List all notes for a user."""
        items = await self.repo.list_user_items(
            user_id=user_id,
            status_filter=status_filter,
            type_filter="NOTE",
        )
        return [ItemResponse.model_validate(i) for i in items]

    async def soft_delete_note(
        self,
        item_id: UUID,
        user_id: UUID,
    ) -> ItemResponse:
        """Soft-delete a note with ownership and type check."""
        item = await self.repo.get_by_id_and_user(item_id, user_id)
        if not item:
            raise ItemNotFoundError(str(item_id))

        if item.type != "NOTE":
            raise ItemNotFoundError(str(item_id))

        before = {"status": item.status, "deleted_at": None}

        deleted_item = await self.repo.soft_delete(item_id)

        await self.event_repo.create(
            item_id=item_id,
            conversation_id=item.conversation_id,
            event_type="DELETED",
            before=before,
            after={"status": deleted_item.status, "deleted_at": deleted_item.deleted_at.isoformat()},
        )

        return ItemResponse.model_validate(deleted_item)

    async def convert_note_to_task(
        self,
        item_id: UUID,
        user_id: UUID,
        due_date: datetime,
    ) -> ConvertNoteToTaskResponse:
        """Convert a note to a task, checking for scheduling conflicts."""
        item = await self.repo.get_by_id_and_user(item_id, user_id)
        if not item:
            raise ItemNotFoundError(str(item_id))

        if item.type != "NOTE":
            raise ItemNotFoundError(str(item_id))

        # Check for conflicts at the requested due_date
        conflicts = await self.repo.find_conflicting_items(
            user_id=user_id,
            target_time=due_date,
            window_minutes=30,
            exclude_item_ids=[item_id],
        )

        if not conflicts:
            # No conflict – convert directly
            before = {"type": item.type, "due_at": None, "status": item.status}

            updated = await self.repo.update(
                item_id,
                type="TASK",
                due_at=due_date,
            )

            await self.event_repo.create(
                item_id=item_id,
                conversation_id=item.conversation_id,
                event_type="UPDATED",
                before=before,
                after={
                    "type": updated.type,
                    "due_at": updated.due_at.isoformat() if updated.due_at else None,
                    "status": updated.status,
                },
            )

            return ConvertNoteToTaskResponse(
                conflict=False,
                item=ItemResponse.model_validate(updated),
            )

        # Conflict exists – build suggestions
        candidate_offsets = [
            timedelta(hours=1),
            timedelta(hours=2),
            timedelta(days=1),
        ]

        suggestions: list[str] = []
        for offset in candidate_offsets:
            candidate = due_date + offset
            candidate_conflicts = await self.repo.find_conflicting_items(
                user_id=user_id,
                target_time=candidate,
                window_minutes=30,
                exclude_item_ids=[item_id],
            )
            if not candidate_conflicts:
                suggestions.append(candidate.isoformat())

        return ConvertNoteToTaskResponse(
            conflict=True,
            conflicting_task=ItemResponse.model_validate(conflicts[0]),
            suggestions=suggestions if suggestions else None,
        )
