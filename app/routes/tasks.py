"""Task endpoints - Legacy compatibility layer.

This module provides backward compatibility for task-specific endpoints.
New code should use /v1/items endpoints directly.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.core.errors import TaskNotFoundError
from app.db.models.user import User
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.item_repo import ItemRepository
from app.db.session import get_session
from app.schemas.enums import ItemStatus
from app.schemas.tasks import TaskListStatus, TaskResponse
from app.services.tasks_service import TasksService

router = APIRouter()


@router.get("/tasks")
async def list_all_tasks(
    date_from: date | None = Query(None, description="Filter tasks with due_at >= this date (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Filter tasks with due_at < day after this date (YYYY-MM-DD)"),
    status: TaskListStatus = Query("all", description="Filter by status: all, active, cancelled, done"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TaskResponse]:
    """
    List all tasks for the current user across all conversations.
    
    This endpoint is provided for backward compatibility.
    Consider using GET /v1/items?type=task for new integrations.
    
    Query parameters:
    - date_from: Filter tasks with due_at >= start of this date (UTC)
    - date_to: Filter tasks with due_at < start of (date_to + 1 day) (UTC)
    - status: "all" (default), "active", "cancelled", or "done"
    
    Returns tasks sorted by due_at ascending (nulls last), then created_at descending.
    """
    service = TasksService(session)
    return await service.list_user_tasks(
        user_id=current_user.id,
        date_from=date_from,
        date_to=date_to,
        status_filter=status,
    )


@router.get("/conversations/{conversation_id}/tasks")
async def list_tasks(
    conversation_id: UUID,
    status: ItemStatus | None = Query(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TaskResponse]:
    """
    List tasks for a conversation.
    
    This endpoint is provided for backward compatibility.
    Consider using GET /v1/conversations/{id}/items?type=task for new integrations.
    """
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
    
    service = TasksService(session)
    return await service.list_tasks(conversation_id, current_user.id, status)


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TaskResponse:
    """
    Get a single task.
    
    This endpoint is provided for backward compatibility.
    Consider using GET /v1/items/{id} for new integrations.
    """
    service = TasksService(session)
    task = await service.get_task(task_id, current_user.id)
    
    if not task:
        raise TaskNotFoundError(str(task_id))
    
    return task

@router.post("/tasks/{task_id}/complete", status_code=http_status.HTTP_204_NO_CONTENT)
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Mark a task as complete.
    
    This endpoint is provided for backward compatibility.
    Consider using PATCH /v1/items/{id} with status=done for new integrations.
    """
    # Verify task ownership
    item_repo = ItemRepository(session)
    item = await item_repo.get_by_id_and_user(task_id, current_user.id)
    if not item or item.type != "TASK":
        raise TaskNotFoundError(str(task_id))
    
    await item_repo.mark_as_complete(task_id)
    await session.commit()

@router.post("/tasks/{task_id}/complete_toggle", status_code=http_status.HTTP_204_NO_CONTENT)
async def toggle_complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Toggle a task's completion status.
    
    This endpoint is provided for backward compatibility.
    Consider using PATCH /v1/items/{id} with status=done or active for new integrations.
    """
    # Verify task ownership
    item_repo = ItemRepository(session)
    item = await item_repo.get_by_id_and_user(task_id, current_user.id)
    if not item or item.type != "TASK":
        raise TaskNotFoundError(str(task_id))
    
    await item_repo.toggle_complete(task_id)
    await session.commit()