"""Test conflict-aware confirmation flow for proposals."""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.proposal import Proposal
from app.db.models.task import Task
from app.db.models.user import User
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.db.repositories.task_repo import TaskRepository
from app.db.repositories.user_repo import UserRepository
from app.schemas.enums import (
    ClarificationField,
    ConfirmAction,
    OpType,
    ProposalStatus,
    TaskRefType,
    TaskStatus,
)
from app.schemas.proposals import (
    Clarification,
    ClarificationContext,
    ConfirmRequest,
    ConfirmUpdate,
    ConflictInfo,
    LlmProposalPayload,
    TaskOp,
    TaskRef,
    TimeSuggestion,
    UpcomingTaskSummary,
)
from app.services.proposals_service import ProposalsService
from app.utils.ids import generate_clarification_id


class TestConflictDetection:
    """Test conflict detection functionality."""

    @pytest.mark.asyncio
    async def test_detect_conflicts_finds_task_in_window(
        self, test_db_session: AsyncSession
    ):
        """Test that conflict detection finds tasks within the window."""
        # Create user
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        # Create conversation
        conversation = Conversation(user_id=user.id, title="Test", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        # Create existing task at 7 PM
        task_repo = TaskRepository(test_db_session)
        target_time = datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        existing_task = await task_repo.create(
            conversation_id=conversation.id,
            title="Meet mom",
            due_at=target_time,
            status="active",
        )
        await test_db_session.commit()

        # Check for conflicts at 7:15 PM (within 30 min window)
        service = ProposalsService(test_db_session)
        conflicts = await service.detect_conflicts(
            user_id=user.id,
            target_time=target_time + timedelta(minutes=15),
            window_minutes=30,
        )

        assert len(conflicts) == 1
        assert conflicts[0].task_id == existing_task.id
        assert conflicts[0].title == "Meet mom"

    @pytest.mark.asyncio
    async def test_detect_conflicts_ignores_task_outside_window(
        self, test_db_session: AsyncSession
    ):
        """Test that conflict detection ignores tasks outside the window."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        task_repo = TaskRepository(test_db_session)
        # Task at 5 PM
        await task_repo.create(
            conversation_id=conversation.id,
            title="Earlier task",
            due_at=datetime(2026, 1, 29, 17, 0, 0, tzinfo=ZoneInfo("UTC")),
            status="active",
        )
        await test_db_session.commit()

        # Check for conflicts at 7 PM (2 hours later, outside 30 min window)
        service = ProposalsService(test_db_session)
        conflicts = await service.detect_conflicts(
            user_id=user.id,
            target_time=datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC")),
            window_minutes=30,
        )

        assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_detect_conflicts_ignores_cancelled_tasks(
        self, test_db_session: AsyncSession
    ):
        """Test that conflict detection ignores cancelled tasks."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        task_repo = TaskRepository(test_db_session)
        target_time = datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        await task_repo.create(
            conversation_id=conversation.id,
            title="Cancelled task",
            due_at=target_time,
            status="cancelled",
        )
        await test_db_session.commit()

        service = ProposalsService(test_db_session)
        conflicts = await service.detect_conflicts(
            user_id=user.id,
            target_time=target_time,
            window_minutes=30,
        )

        assert len(conflicts) == 0


class TestUpcomingTasksContext:
    """Test upcoming tasks context generation."""

    @pytest.mark.asyncio
    async def test_get_upcoming_tasks_context(self, test_db_session: AsyncSession):
        """Test that upcoming tasks context includes nearby tasks."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        task_repo = TaskRepository(test_db_session)
        reference_time = datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC"))

        # Create tasks around reference time
        await task_repo.create(
            conversation_id=conversation.id,
            title="Task before",
            due_at=reference_time - timedelta(hours=2),
            status="active",
        )
        await task_repo.create(
            conversation_id=conversation.id,
            title="Task after",
            due_at=reference_time + timedelta(hours=1),
            status="active",
        )
        # Task outside window
        await task_repo.create(
            conversation_id=conversation.id,
            title="Far task",
            due_at=reference_time + timedelta(hours=5),
            status="active",
        )
        await test_db_session.commit()

        service = ProposalsService(test_db_session)
        context = await service.get_upcoming_tasks_context(
            user_id=user.id,
            reference_time=reference_time,
            window_hours=3,
        )

        assert context.window_start == reference_time - timedelta(hours=3)
        assert context.window_end == reference_time + timedelta(hours=3)
        assert len(context.upcoming_tasks) == 2
        titles = [t.title for t in context.upcoming_tasks]
        assert "Task before" in titles
        assert "Task after" in titles
        assert "Far task" not in titles


class TestAlternativeSuggestions:
    """Test alternative time suggestion generation."""

    @pytest.mark.asyncio
    async def test_generate_conflict_free_alternatives(
        self, test_db_session: AsyncSession
    ):
        """Test that alternative suggestions avoid conflicts."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        task_repo = TaskRepository(test_db_session)
        original_time = datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC"))

        # Create task at +60 min to force using +90 min suggestion
        await task_repo.create(
            conversation_id=conversation.id,
            title="Blocking task",
            due_at=original_time + timedelta(minutes=60),
            status="active",
        )
        await test_db_session.commit()

        service = ProposalsService(test_db_session)
        suggestions = await service.generate_alternative_suggestions(
            user_id=user.id,
            original_time=original_time,
            timezone="UTC",
            max_suggestions=2,
        )

        # Should skip +60min (blocked) and include +90min and next day
        assert len(suggestions) >= 1
        # First suggestion should be +90 min
        assert suggestions[0].due_at == original_time + timedelta(minutes=90)


class TestConfirmProposalEndpoint:
    """Test the confirm proposal endpoint."""

    @pytest.mark.asyncio
    async def test_confirm_replace_existing_cancels_old_task(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that replace_existing action cancels the conflicting task."""
        # Create user
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        # Create conversation
        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        # Create existing task that will conflict
        task_repo = TaskRepository(test_db_session)
        conflict_time = datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        existing_task = await task_repo.create(
            conversation_id=conversation.id,
            title="Meet mom",
            due_at=conflict_time,
            status="active",
        )

        clarification_id = generate_clarification_id()

        # Create proposal with conflict clarification
        proposal_payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="new_task",
                    title="Meet friends",
                    due_at=conflict_time.isoformat(),
                )
            ],
            needs_confirmation=True,
            clarifications=[
                Clarification(
                    clarification_id=clarification_id,
                    field=ClarificationField.CONFLICT,
                    target_temp_id="new_task",
                    message="Conflict detected",
                    conflict=ConflictInfo(
                        existing_task=UpcomingTaskSummary(
                            task_id=existing_task.id,
                            conversation_id=conversation.id,
                            title="Meet mom",
                            due_at=conflict_time,
                            status=TaskStatus.ACTIVE,
                        ),
                        proposed_due_at=conflict_time,
                        window_minutes=30,
                    ),
                    available_actions=["replace_existing", "reschedule_new", "cancel_new"],
                )
            ],
        )

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=proposal_payload.model_dump(mode="json"),
        )
        await test_db_session.commit()

        # Get auth token
        from app.auth.security import create_access_token

        access_token = create_access_token(user_id=user.id)

        # Call confirm endpoint with replace_existing
        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "updates": [],
                "action": "replace_existing",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is True
        assert data["tasks_affected"] == 1
        assert data["tasks_canceled"] == 1

        # Verify old task was cancelled
        await test_db_session.refresh(existing_task)
        assert existing_task.status == "cancelled"

        # Verify new task was created
        tasks = await task_repo.list_by_conversation(conversation.id)
        active_tasks = [t for t in tasks if t.status == "active"]
        assert len(active_tasks) == 1
        assert active_tasks[0].title == "Meet friends"

    @pytest.mark.asyncio
    async def test_confirm_cancel_new_does_not_create_task(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that cancel_new action cancels the proposal without creating task."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        clarification_id = generate_clarification_id()

        proposal_payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="new_task",
                    title="New task",
                    due_at="2026-01-29T19:00:00Z",
                )
            ],
            needs_confirmation=True,
            clarifications=[
                Clarification(
                    clarification_id=clarification_id,
                    field=ClarificationField.DUE_AT,
                    target_temp_id="new_task",
                    message="Confirm time",
                )
            ],
        )

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=proposal_payload.model_dump(mode="json"),
        )
        await test_db_session.commit()

        from app.auth.security import create_access_token

        access_token = create_access_token(user_id=user.id)

        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "updates": [],
                "action": "cancel_new",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is False
        assert data["status"] == "canceled"
        assert data["tasks_affected"] == 0

        # Verify no tasks were created
        task_repo = TaskRepository(test_db_session)
        tasks = await task_repo.list_by_conversation(conversation.id)
        assert len(tasks) == 0

        # Verify proposal status
        await test_db_session.refresh(proposal)
        assert proposal.status == "canceled"

    @pytest.mark.asyncio
    async def test_confirm_reschedule_new_to_conflict_free_time(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that reschedule_new with conflict-free time applies successfully."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        clarification_id = generate_clarification_id()
        new_time = datetime(2026, 1, 29, 20, 0, 0, tzinfo=ZoneInfo("UTC"))

        proposal_payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="new_task",
                    title="New task",
                    due_at="2026-01-29T19:00:00Z",  # Original conflicting time
                )
            ],
            needs_confirmation=True,
            clarifications=[
                Clarification(
                    clarification_id=clarification_id,
                    field=ClarificationField.CONFLICT,
                    target_temp_id="new_task",
                    message="Conflict detected",
                    available_actions=["replace_existing", "reschedule_new", "cancel_new"],
                )
            ],
        )

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=proposal_payload.model_dump(mode="json"),
        )
        await test_db_session.commit()

        from app.auth.security import create_access_token

        access_token = create_access_token(user_id=user.id)

        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "updates": [
                    {
                        "clarification_id": clarification_id,
                        "due_at": new_time.isoformat(),
                        "timezone": "UTC",
                    }
                ],
                "action": "reschedule_new",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is True
        assert data["tasks_affected"] == 1
        assert data["needs_further_confirmation"] is False

        # Verify task was created at new time
        task_repo = TaskRepository(test_db_session)
        tasks = await task_repo.list_by_conversation(conversation.id)
        assert len(tasks) == 1
        assert tasks[0].due_at.hour == 20

    @pytest.mark.asyncio
    async def test_confirm_reschedule_new_to_another_conflict(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that reschedule_new to another conflicting time returns needs_confirmation."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        # Create another conflicting task at the new time
        task_repo = TaskRepository(test_db_session)
        new_conflict_time = datetime(2026, 1, 29, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
        await task_repo.create(
            conversation_id=conversation.id,
            title="Another task",
            due_at=new_conflict_time,
            status="active",
        )

        clarification_id = generate_clarification_id()

        proposal_payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="new_task",
                    title="New task",
                    due_at="2026-01-29T19:00:00Z",
                )
            ],
            needs_confirmation=True,
            clarifications=[
                Clarification(
                    clarification_id=clarification_id,
                    field=ClarificationField.CONFLICT,
                    target_temp_id="new_task",
                    message="Conflict detected",
                    available_actions=["replace_existing", "reschedule_new", "cancel_new"],
                )
            ],
        )

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=proposal_payload.model_dump(mode="json"),
        )
        await test_db_session.commit()

        from app.auth.security import create_access_token

        access_token = create_access_token(user_id=user.id)

        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "updates": [
                    {
                        "clarification_id": clarification_id,
                        "due_at": new_conflict_time.isoformat(),
                        "timezone": "UTC",
                    }
                ],
                "action": "reschedule_new",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is False
        assert data["status"] == "needs_confirmation"
        assert data["needs_further_confirmation"] is True
        assert len(data["clarifications"]) == 1
        assert data["clarifications"][0]["field"] == "conflict"

    @pytest.mark.asyncio
    async def test_confirm_idempotency_already_applied(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that confirming an already applied proposal returns success."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.APPLIED.value,
            ops={"ops": [], "needs_confirmation": False},
        )
        await test_db_session.commit()

        from app.auth.security import create_access_token

        access_token = create_access_token(user_id=user.id)

        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"updates": [], "action": "apply"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is True
        assert data["status"] == "applied"
        assert data["tasks_affected"] == 0

    @pytest.mark.asyncio
    async def test_confirm_idempotency_already_canceled(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that confirming an already canceled proposal returns correct status."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.CANCELED.value,
        )
        await test_db_session.commit()

        from app.auth.security import create_access_token

        access_token = create_access_token(user_id=user.id)

        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"updates": [], "action": "apply"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is False
        assert data["status"] == "canceled"


class TestClarificationWithContext:
    """Test that clarifications include proper context."""

    @pytest.mark.asyncio
    async def test_due_at_clarification_includes_upcoming_tasks(
        self, test_db_session: AsyncSession
    ):
        """Test that due_at clarifications include upcoming tasks context."""
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        conversation = Conversation(user_id=user.id, title="Test", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        # Create existing tasks
        task_repo = TaskRepository(test_db_session)
        reference_time = datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        await task_repo.create(
            conversation_id=conversation.id,
            title="Nearby task",
            due_at=reference_time + timedelta(hours=1),
            status="active",
        )
        await test_db_session.commit()

        # Create clarification with context enrichment
        from app.workers.tasks import _enrich_clarifications_with_context
        from app.schemas.proposals import Clarification, TimeSuggestion
        from app.schemas.enums import ClarificationField
        from app.utils.ids import generate_clarification_id

        payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="New task",
                )
            ],
            needs_confirmation=True,
            clarifications=[
                Clarification(
                    clarification_id=generate_clarification_id(),
                    field=ClarificationField.DUE_AT,
                    target_temp_id="task_1",
                    message="When?",
                    suggestions=[
                        TimeSuggestion(
                            due_at=reference_time,
                            timezone="UTC",
                            label="7 PM",
                            confidence=0.7,
                        )
                    ],
                )
            ],
        )

        enriched = await _enrich_clarifications_with_context(
            payload, user.id, task_repo, "UTC"
        )

        assert len(enriched.clarifications) == 1
        clarification = enriched.clarifications[0]
        assert clarification.context is not None
        assert len(clarification.context.upcoming_tasks) >= 1
        assert clarification.context.upcoming_tasks[0].title == "Nearby task"
