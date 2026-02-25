"""Test time confirmation flow for proposals."""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.proposal import Proposal
from app.db.models.user import User
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.db.repositories.task_repo import TaskRepository
from app.db.repositories.user_repo import UserRepository
from app.schemas.enums import ClarificationField, OpType, ProposalStatus, TaskRefType
from app.schemas.proposals import (
    Clarification,
    LlmProposalPayload,
    TaskOp,
    TaskRef,
    TimeSuggestion,
)
from app.workers.tasks import _enforce_time_confirmation


class TestTimeConfirmationGating:
    """Test the _enforce_time_confirmation function."""

    def test_no_missing_time_returns_unchanged(self):
        """Test that payload with due_at set is returned unchanged."""
        payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Meeting",
                    due_at="2026-01-29T19:00:00Z",
                )
            ],
            needs_confirmation=False,
        )

        result = _enforce_time_confirmation(payload, "UTC")

        assert result.needs_confirmation is False
        assert len(result.clarifications) == 0

    def test_missing_time_sets_needs_confirmation(self):
        """Test that missing due_at forces needs_confirmation=true."""
        payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Meeting",
                    due_at=None,  # Missing time
                )
            ],
            needs_confirmation=False,
        )

        result = _enforce_time_confirmation(payload, "UTC")

        assert result.needs_confirmation is True

    def test_missing_time_adds_clarification(self):
        """Test that missing due_at adds clarification."""
        payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Important Meeting",
                    due_at=None,
                )
            ],
            needs_confirmation=False,
            clarifications=[],
        )

        result = _enforce_time_confirmation(payload, "Europe/Istanbul")

        assert len(result.clarifications) == 1
        clarification = result.clarifications[0]
        assert clarification.field == ClarificationField.DUE_AT
        assert clarification.op_ref.type == TaskRefType.TEMP_ID
        assert clarification.op_ref.value == "task_1"
        assert "Important Meeting" in clarification.message
        assert len(clarification.suggestions) >= 1

    def test_missing_time_uses_llm_suggestion_if_available(self):
        """Test that LLM suggestions are used if provided."""
        suggested_time = datetime(2026, 1, 30, 18, 0, 0, tzinfo=ZoneInfo("UTC"))
        payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Meeting",
                    due_at=None,
                    suggested_due_at=suggested_time,
                    suggested_timezone="Europe/Istanbul",
                    suggested_confidence=0.8,
                )
            ],
            needs_confirmation=False,
            clarifications=[],
        )

        result = _enforce_time_confirmation(payload, "Europe/Istanbul")

        assert len(result.clarifications) == 1
        suggestion = result.clarifications[0].suggestions[0]
        assert suggestion.due_at == suggested_time
        assert suggestion.timezone == "Europe/Istanbul"
        assert suggestion.confidence == 0.8

    def test_missing_time_fallback_suggestion_before_7pm(self):
        """Test fallback suggestion uses today 7 PM if before 7 PM."""
        payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Task",
                    due_at=None,
                )
            ],
            needs_confirmation=False,
            clarifications=[],
        )

        result = _enforce_time_confirmation(payload, "UTC")

        assert len(result.clarifications) == 1
        suggestion = result.clarifications[0].suggestions[0]
        assert suggestion.confidence == 0.3  # Low confidence for fallback
        # Suggestion should be at 19:00
        assert suggestion.due_at.hour == 19
        assert suggestion.due_at.minute == 0

    def test_multiple_missing_times_add_multiple_clarifications(self):
        """Test that each op with missing time gets its own clarification."""
        payload = LlmProposalPayload(
            ops=[
                TaskOp(op=OpType.CREATE, temp_id="task_1", title="Task 1", due_at=None),
                TaskOp(
                    op=OpType.CREATE, temp_id="task_2", title="Task 2", due_at="2026-01-30T10:00:00Z"
                ),
                TaskOp(op=OpType.CREATE, temp_id="task_3", title="Task 3", due_at=None),
            ],
            needs_confirmation=False,
            clarifications=[],
        )

        result = _enforce_time_confirmation(payload, "UTC")

        assert result.needs_confirmation is True
        assert len(result.clarifications) == 2  # task_1 and task_3
        temp_ids = [c.op_ref.value for c in result.clarifications]
        assert "task_1" in temp_ids
        assert "task_3" in temp_ids


class TestConfirmTimeEndpoint:
    """Test the confirm-time endpoint."""

    @pytest.mark.asyncio
    async def test_confirm_time_applies_proposal(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that confirm-time endpoint applies the proposal."""
        # Create user
        user_repo = UserRepository(test_db_session)
        user = await user_repo.create(
            client_uuid=uuid4(),
            kind="GUEST",
        )

        # Create conversation
        conversation = Conversation(user_id=user.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        # Create proposal with needs_confirmation
        proposal_payload = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Meeting",
                    due_at=None,
                )
            ],
            needs_confirmation=True,
            clarifications=[
                Clarification(
                    clarification_id="clr_test_123",
                    field=ClarificationField.DUE_AT,
                    target_temp_id="task_1",
                    op_ref=TaskRef(type=TaskRefType.TEMP_ID, value="task_1"),
                    message="When?",
                    suggestions=[
                        TimeSuggestion(
                            due_at=datetime(2026, 1, 29, 19, 0, 0, tzinfo=ZoneInfo("UTC")),
                            timezone="UTC",
                            label="7 PM",
                            confidence=0.7,
                        )
                    ],
                )
            ],
        )

        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),  # Mock message ID
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

        # Call confirm-time endpoint
        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm-time",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "updates": [
                    {
                        "ref": {"type": "temp_id", "value": "task_1"},
                        "due_at": "2026-01-29T20:00:00Z",
                        "timezone": "UTC",
                    }
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is True
        assert data["tasks_affected"] == 1

        # Verify task was created
        task_repo = TaskRepository(test_db_session)
        tasks = await task_repo.list_by_conversation(conversation.id)
        assert len(tasks) == 1
        assert tasks[0].title == "Meeting"
        assert tasks[0].due_at.hour == 20

    @pytest.mark.asyncio
    async def test_confirm_time_forbidden_for_other_user(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that confirm-time returns 403 for proposals not belonging to user."""
        # Create two users
        user_repo = UserRepository(test_db_session)
        owner = await user_repo.create(client_uuid=uuid4(), kind="GUEST")
        other_user = await user_repo.create(client_uuid=uuid4(), kind="GUEST")

        # Create conversation for owner
        conversation = Conversation(user_id=owner.id, title="Test Conv", version=1)
        test_db_session.add(conversation)
        await test_db_session.flush()

        # Create proposal
        proposal_repo = ProposalRepository(test_db_session)
        proposal = await proposal_repo.create(
            conversation_id=conversation.id,
            message_id=uuid4(),
            version=1,
        )
        await proposal_repo.update_status(
            proposal.id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops={"ops": [], "needs_confirmation": True},
        )
        await test_db_session.commit()

        # Try with other user's token
        from app.auth.security import create_access_token

        other_token = create_access_token(user_id=other_user.id)

        response = await client.post(
            f"/v1/proposals/{proposal.id}/confirm-time",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"updates": []},
        )

        assert response.status_code == 403
