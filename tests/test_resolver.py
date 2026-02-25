"""Tests for resolver service."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.task_repo import TaskRepository
from app.schemas.enums import TaskRefType
from app.schemas.proposals import TaskOp, TaskRef
from app.services.resolver_service import ResolverService


@pytest.mark.asyncio
async def test_resolve_task_id_reference(test_session: AsyncSession):
    """Test resolving a direct task_id reference."""
    resolver = ResolverService(test_session)
    
    # Create a task
    task_repo = TaskRepository(test_session)
    task = await task_repo.create(
        conversation_id=uuid4(),
        title="Test Task",
    )
    await test_session.commit()
    
    # Create reference
    ref = TaskRef(type=TaskRefType.TASK_ID, value=str(task.id))
    
    # Resolve
    resolution = await resolver._resolve_ref(task.conversation_id, ref, "UTC")
    
    assert resolution.resolved_task_id == task.id
    assert resolution.confidence == 1.0
    assert not resolution.requires_confirmation


@pytest.mark.asyncio
async def test_resolve_natural_reference_by_time(test_session: AsyncSession):
    """Test resolving a natural language reference with time."""
    conversation_id = uuid4()
    resolver = ResolverService(test_session)
    task_repo = TaskRepository(test_session)
    
    # Create tasks at different times
    now = datetime.now()
    task1 = await task_repo.create(
        conversation_id=conversation_id,
        title="Morning Meeting",
        due_at=now.replace(hour=9, minute=0),
    )
    task2 = await task_repo.create(
        conversation_id=conversation_id,
        title="Evening Call",
        due_at=now.replace(hour=19, minute=0),
    )
    await test_session.commit()
    
    # Reference to "7pm task"
    ref = TaskRef(type=TaskRefType.NATURAL, value="task at 7pm")
    
    # Resolve
    resolution = await resolver._resolve_ref(conversation_id, ref, "UTC")
    
    # Should find the 7pm (19:00) task
    assert resolution.resolved_task_id == task2.id
    assert resolution.confidence > 0.5
    assert len(resolution.candidates) > 0


@pytest.mark.asyncio
async def test_resolve_ambiguous_reference(test_session: AsyncSession):
    """Test that ambiguous references require confirmation."""
    conversation_id = uuid4()
    resolver = ResolverService(test_session)
    task_repo = TaskRepository(test_session)
    
    # Create multiple similar tasks
    now = datetime.now()
    task1 = await task_repo.create(
        conversation_id=conversation_id,
        title="Meeting",
        due_at=now.replace(hour=14, minute=0),
    )
    task2 = await task_repo.create(
        conversation_id=conversation_id,
        title="Meeting with Client",
        due_at=now.replace(hour=14, minute=30),
    )
    await test_session.commit()
    
    # Vague reference
    ref = TaskRef(type=TaskRefType.NATURAL, value="the meeting")
    
    # Resolve
    resolution = await resolver._resolve_ref(conversation_id, ref, "UTC")
    
    # Should require confirmation due to ambiguity
    assert resolution.requires_confirmation
    assert len(resolution.candidates) >= 2


@pytest.mark.asyncio
async def test_resolve_operations(test_session: AsyncSession):
    """Test resolving multiple operations."""
    conversation_id = uuid4()
    resolver = ResolverService(test_session)
    task_repo = TaskRepository(test_session)
    
    # Create a task
    task = await task_repo.create(
        conversation_id=conversation_id,
        title="Existing Task",
    )
    await test_session.commit()
    
    # Operations
    ops = [
        TaskOp(
            op="update",
            ref=TaskRef(type=TaskRefType.TASK_ID, value=str(task.id)),
            title="Updated Title",
        ),
        TaskOp(
            op="create",
            temp_id="task_1",
            title="New Task",
        ),
    ]
    
    # Resolve
    resolution = await resolver.resolve_operations(conversation_id, ops, "UTC")
    
    assert len(resolution.resolutions) == 1  # Only update has ref
    assert not resolution.needs_confirmation


@pytest.mark.asyncio
async def test_resolve_no_match(test_session: AsyncSession):
    """Test resolving reference with no matching tasks."""
    conversation_id = uuid4()
    resolver = ResolverService(test_session)
    
    # Reference to non-existent task
    ref = TaskRef(type=TaskRefType.NATURAL, value="nonexistent task")
    
    # Resolve
    resolution = await resolver._resolve_ref(conversation_id, ref, "UTC")
    
    # Should return no match
    assert resolution.resolved_task_id is None
    assert resolution.requires_confirmation
    assert len(resolution.candidates) == 0
