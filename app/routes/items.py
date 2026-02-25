"""Item endpoints."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.core.errors import ItemNotFoundError
from app.db.models.user import User
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.item_repo import ItemRepository
from app.db.session import get_session
from app.schemas.enums import ItemStatus, ItemType
from app.schemas.items import ItemListStatus, ItemListType, ItemResponse
from app.services.items_service import ItemsService

router = APIRouter()


@router.get("/items")
async def list_all_items(
    date_from: date | None = Query(
        None,
        description="Filter tasks with due_at >= this date (YYYY-MM-DD). Notes are not filtered by date."
    ),
    date_to: date | None = Query(
        None,
        description="Filter tasks with due_at < day after this date (YYYY-MM-DD). Notes are not filtered by date."
    ),
    status: ItemListStatus = Query(
        "all",
        description="Filter by status: all, active, done, canceled, archived"
    ),
    type: ItemListType = Query(
        "all",
        description="Filter by type: all, task, note"
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ItemResponse]:
    """
    List all items for the current user across all conversations.
    
    Query parameters:
    - date_from: Filter tasks with due_at >= start of this date (UTC). Notes are not filtered.
    - date_to: Filter tasks with due_at < start of (date_to + 1 day) (UTC). Notes are not filtered.
    - status: "all" (default), "active", "done", "canceled", or "archived"
    - type: "all" (default), "task", or "note"
    
    Returns items with combined sorting:
    - Tasks with due_at first (sorted by due_at ascending)
    - Then notes (pinned first, then by updated_at descending)
    - Tasks without due_at at the end
    """
    # Map status filter
    status_map = {
        "all": None,
        "active": "ACTIVE",
        "done": "DONE",
        "canceled": "CANCELED",
        "archived": "ARCHIVED",
    }
    status_filter = status_map.get(status)
    
    # Map type filter
    type_map = {
        "all": None,
        "task": "TASK",
        "note": "NOTE",
    }
    type_filter = type_map.get(type)
    
    service = ItemsService(session)
    return await service.list_user_items(
        user_id=current_user.id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
        type_filter=type_filter,
    )


@router.get("/conversations/{conversation_id}/items")
async def list_conversation_items(
    conversation_id: UUID,
    status: ItemStatus | None = Query(None, description="Filter by status"),
    type: ItemType | None = Query(None, description="Filter by type"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ItemResponse]:
    """List items for a conversation."""
    # Verify conversation ownership
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_id_and_user(
        conversation_id, current_user.id
    )
    if not conversation:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Conversation not found or access denied",
        )
    
    service = ItemsService(session)
    return await service.list_items(
        conversation_id,
        user_id=current_user.id,
        status=status,
        item_type=type,
    )


@router.get("/items/{item_id}")
async def get_item(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ItemResponse:
    """Get a single item."""
    service = ItemsService(session)
    item = await service.get_item(item_id, current_user.id)
    
    if not item:
        raise ItemNotFoundError(str(item_id))
    
    return item
