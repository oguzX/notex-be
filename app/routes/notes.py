"""Note endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.items import ItemResponse
from app.schemas.notes import (
    ConvertNoteToTaskRequest,
    ConvertNoteToTaskResponse,
    NoteListStatus,
)
from app.services.notes_service import NotesService

router = APIRouter()


@router.get("/notes")
async def list_notes(
    status: NoteListStatus = Query(
        "all",
        description="Filter by status: all, active, archived",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ItemResponse]:
    """List all notes for the current user.

    Query parameters:
    - status: "all" (default), "active", or "archived"

    Returns notes sorted by pinned first, then by updated_at descending.
    """
    status_map = {
        "all": None,
        "active": "ACTIVE",
        "archived": "ARCHIVED",
    }
    status_filter = status_map.get(status)

    service = NotesService(session)
    return await service.list_notes(
        user_id=current_user.id,
        status_filter=status_filter,
    )


@router.delete("/notes/{item_id}")
async def delete_note(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ItemResponse:
    """Soft-delete a note.

    Returns 404 if the item doesn't exist, doesn't belong to the user,
    or is not a NOTE.
    """
    service = NotesService(session)
    return await service.soft_delete_note(item_id, current_user.id)


@router.post("/notes/{item_id}/convert-to-task")
async def convert_note_to_task(
    item_id: UUID,
    body: ConvertNoteToTaskRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConvertNoteToTaskResponse:
    """Convert a note to a task with the given due_date.

    If the user already has a task within +-30 minutes of the requested
    due_date, returns conflict=True with alternative time suggestions
    (+1h, +2h, +1d — only those that are also conflict-free).

    The client can retry with a selected suggestion using the same endpoint.
    """
    service = NotesService(session)
    return await service.convert_note_to_task(
        item_id=item_id,
        user_id=current_user.id,
        due_date=body.due_date,
    )
