"""Test list all tasks endpoint."""

from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.task import Task
from app.db.models.user import User
from app.db.repositories.task_repo import TaskRepository
from app.db.repositories.user_repo import UserRepository


class TestListAllTasks:
    """Test GET /v1/tasks endpoint."""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_only_user_tasks(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that endpoint only returns tasks for current user."""
        user_repo = UserRepository(test_db_session)

        # Create two users
        user1 = await user_repo.create(client_uuid=uuid4(), kind="GUEST")
        user2 = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        # Create conversations for each user
        conv1 = Conversation(user_id=user1.id, title="User1 Conv", version=1)
        conv2 = Conversation(user_id=user2.id, title="User2 Conv", version=1)
        test_db_session.add_all([conv1, conv2])
        await test_db_session.flush()

        # Create tasks for each user
        task1 = Task(
            conversation_id=conv1.id,
            title="User1 Task",
            status="active",
            priority="medium",
        )
        task2 = Task(
            conversation_id=conv2.id,
            title="User2 Task",
            status="active",
            priority="medium",
        )
        test_db_session.add_all([task1, task2])
        await test_db_session.commit()

        # Get user1's tasks
        from app.auth.security import create_access_token

        token1 = create_access_token(user_id=user1.id)
        response = await client.get(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "User1 Task"

    @pytest.mark.asyncio
    async def test_list_tasks_date_from_filter(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test date_from filter works correctly."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conv = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conv)
        await test_db_session.flush()

        # Create tasks with different due dates
        task_early = Task(
            conversation_id=conv.id,
            title="Early Task",
            due_at=datetime(2026, 1, 20, 10, 0, 0),
            status="active",
            priority="medium",
        )
        task_late = Task(
            conversation_id=conv.id,
            title="Late Task",
            due_at=datetime(2026, 1, 30, 10, 0, 0),
            status="active",
            priority="medium",
        )
        test_db_session.add_all([task_early, task_late])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        # Filter from Jan 25
        response = await client.get(
            "/v1/tasks?date_from=2026-01-25",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Late Task"

    @pytest.mark.asyncio
    async def test_list_tasks_date_to_filter(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test date_to filter works correctly."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conv = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conv)
        await test_db_session.flush()

        # Create tasks with different due dates
        task_early = Task(
            conversation_id=conv.id,
            title="Early Task",
            due_at=datetime(2026, 1, 20, 10, 0, 0),
            status="active",
            priority="medium",
        )
        task_late = Task(
            conversation_id=conv.id,
            title="Late Task",
            due_at=datetime(2026, 1, 30, 10, 0, 0),
            status="active",
            priority="medium",
        )
        test_db_session.add_all([task_early, task_late])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        # Filter to Jan 25
        response = await client.get(
            "/v1/tasks?date_to=2026-01-25",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Early Task"

    @pytest.mark.asyncio
    async def test_list_tasks_status_filter_active(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test status=active filter works correctly."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conv = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conv)
        await test_db_session.flush()

        # Create tasks with different statuses
        task_active = Task(
            conversation_id=conv.id,
            title="Active Task",
            status="active",
            priority="medium",
        )
        task_cancelled = Task(
            conversation_id=conv.id,
            title="Cancelled Task",
            status="cancelled",
            priority="medium",
        )
        task_done = Task(
            conversation_id=conv.id,
            title="Done Task",
            status="done",
            priority="medium",
        )
        test_db_session.add_all([task_active, task_cancelled, task_done])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        response = await client.get(
            "/v1/tasks?status=active",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Active Task"

    @pytest.mark.asyncio
    async def test_list_tasks_status_filter_all(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test status=all includes all statuses."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conv = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conv)
        await test_db_session.flush()

        # Create tasks with different statuses
        task_active = Task(
            conversation_id=conv.id,
            title="Active Task",
            status="active",
            priority="medium",
        )
        task_cancelled = Task(
            conversation_id=conv.id,
            title="Cancelled Task",
            status="cancelled",
            priority="medium",
        )
        test_db_session.add_all([task_active, task_cancelled])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        response = await client.get(
            "/v1/tasks?status=all",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_list_tasks_sorted_by_due_at(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that tasks are sorted by due_at asc, nulls last."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conv = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conv)
        await test_db_session.flush()

        # Create tasks with various due dates
        task_no_due = Task(
            conversation_id=conv.id,
            title="No Due Date",
            due_at=None,
            status="active",
            priority="medium",
        )
        task_later = Task(
            conversation_id=conv.id,
            title="Later Task",
            due_at=datetime(2026, 1, 30, 10, 0, 0),
            status="active",
            priority="medium",
        )
        task_earlier = Task(
            conversation_id=conv.id,
            title="Earlier Task",
            due_at=datetime(2026, 1, 25, 10, 0, 0),
            status="active",
            priority="medium",
        )
        test_db_session.add_all([task_no_due, task_later, task_earlier])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        response = await client.get(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 3

        # Check order: earlier, later, no_due (nulls last)
        assert tasks[0]["title"] == "Earlier Task"
        assert tasks[1]["title"] == "Later Task"
        assert tasks[2]["title"] == "No Due Date"

    @pytest.mark.asyncio
    async def test_list_tasks_across_multiple_conversations(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that tasks from all user's conversations are returned."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        # Create multiple conversations
        conv1 = Conversation(user_id=user.id, title="Conv 1", version=1)
        conv2 = Conversation(user_id=user.id, title="Conv 2", version=1)
        test_db_session.add_all([conv1, conv2])
        await test_db_session.flush()

        # Create tasks in each conversation
        task1 = Task(
            conversation_id=conv1.id,
            title="Task from Conv1",
            status="active",
            priority="medium",
        )
        task2 = Task(
            conversation_id=conv2.id,
            title="Task from Conv2",
            status="active",
            priority="medium",
        )
        test_db_session.add_all([task1, task2])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        response = await client.get(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 2
        titles = {t["title"] for t in tasks}
        assert "Task from Conv1" in titles
        assert "Task from Conv2" in titles

    @pytest.mark.asyncio
    async def test_list_tasks_excludes_deleted(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that soft-deleted tasks are excluded."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conv = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conv)
        await test_db_session.flush()

        # Create active and deleted tasks
        task_active = Task(
            conversation_id=conv.id,
            title="Active Task",
            status="active",
            priority="medium",
        )
        task_deleted = Task(
            conversation_id=conv.id,
            title="Deleted Task",
            status="cancelled",
            priority="medium",
            deleted_at=datetime.now(),
        )
        test_db_session.add_all([task_active, task_deleted])
        await test_db_session.commit()

        from app.auth.security import create_access_token

        token = create_access_token(user_id=user.id)

        response = await client.get(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Active Task"

    @pytest.mark.asyncio
    async def test_list_tasks_requires_auth(self, client: AsyncClient):
        """Test that endpoint requires authentication."""
        response = await client.get("/v1/tasks")
        assert response.status_code == 401
