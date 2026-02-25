"""Tests for proposal status logic and needs_confirmation handling."""

from datetime import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

from app.schemas.enums import EventType, OpType, ProposalStatus
from app.schemas.proposals import (
    LlmProposalPayload,
    ProposalResolution,
    TaskOp,
    TaskResolution,
)
from app.workers.tasks import _process_message_async


def _create_mock_message():
    """Create a mock message with created_at timestamp."""
    mock_message = MagicMock()
    mock_message.created_at = datetime(2026, 1, 29, 8, 32, 0)
    return mock_message


def _create_mock_conversation():
    """Create a mock conversation."""
    mock_conversation = MagicMock()
    mock_conversation.id = uuid4()
    mock_conversation.user_id = uuid4()
    return mock_conversation


@pytest.fixture
def mock_dependencies():
    """Mock all dependencies for message processing."""
    with patch("app.workers.tasks.get_event_bus") as mock_event_bus, \
         patch("app.workers.tasks.get_session_factory") as mock_session_factory, \
         patch("app.workers.tasks.get_llm_provider") as mock_llm_provider, \
         patch("app.workers.tasks.ResolverService") as mock_resolver_service, \
         patch("app.workers.tasks.ProposalsService") as mock_proposals_service:
        
        # Setup mock session
        mock_session = AsyncMock()
        mock_session_factory.return_value.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_factory.return_value.return_value.__aexit__ = AsyncMock()
        
        # Setup mock repositories
        mock_session.commit = AsyncMock()
        
        # Setup mock proposal repo
        mock_proposal = MagicMock()
        mock_proposal.id = uuid4()
        mock_proposal.message_id = uuid4()
        mock_proposal.version = 1
        
        # Setup event bus
        mock_event_bus.return_value.publish = AsyncMock()
        
        yield {
            "event_bus": mock_event_bus,
            "session_factory": mock_session_factory,
            "llm_provider": mock_llm_provider,
            "resolver_service": mock_resolver_service,
            "proposals_service": mock_proposals_service,
            "session": mock_session,
            "proposal": mock_proposal,
        }


@pytest.mark.asyncio
async def test_needs_confirmation_with_empty_ops_and_auto_apply(mock_dependencies):
    """
    Test: When LLM returns needs_confirmation=true, ops=[], auto_apply=true
    Expected: status must be needs_confirmation, no task changes, 
              event PROPOSAL_NEEDS_CONFIRMATION emitted
    """
    conversation_id = str(uuid4())
    message_id = str(uuid4())
    version = 1
    
    # Setup mocks
    mocks = mock_dependencies
    # Set mock proposal's message_id to match the test's message_id
    mocks["proposal"].message_id = UUID(message_id)
    
    # Mock proposal repository
    mock_proposal_repo = AsyncMock()
    mock_proposal_repo.list_by_conversation = AsyncMock(return_value=[mocks["proposal"]])
    mock_proposal_repo.update_status = AsyncMock()
    
    # Mock other repositories
    mock_message = _create_mock_message()
    mock_message_repo = AsyncMock()
    mock_message_repo.get_by_id = AsyncMock(return_value=mock_message)
    mock_message_repo.get_recent_context = AsyncMock(return_value=[])
    
    mock_conversation = _create_mock_conversation()
    mock_conversation_repo = AsyncMock()
    mock_conversation_repo.get_version = AsyncMock(return_value=version)
    mock_conversation_repo.get_by_id = AsyncMock(return_value=mock_conversation)
    
    mock_task_repo = AsyncMock()
    mock_task_repo.get_active_snapshot = AsyncMock(return_value=[])
    
    # Patch repository constructors
    with patch("app.workers.tasks.ProposalRepository", return_value=mock_proposal_repo), \
         patch("app.workers.tasks.MessageRepository", return_value=mock_message_repo), \
         patch("app.workers.tasks.ConversationRepository", return_value=mock_conversation_repo), \
         patch("app.workers.tasks.TaskRepository", return_value=mock_task_repo):
        
        # LLM returns empty ops with needs_confirmation=true
        mock_llm_response = LlmProposalPayload(
            ops=[],
            needs_confirmation=True,
            reasoning="User message is unclear, need confirmation"
        )
        mocks["llm_provider"].return_value.generate_proposal = AsyncMock(
            return_value=mock_llm_response
        )
        
        # Resolver returns no resolutions
        mock_resolution = ProposalResolution(
            resolutions=[],
            needs_confirmation=False
        )
        mocks["resolver_service"].return_value.resolve_operations = AsyncMock(
            return_value=mock_resolution
        )
        
        # Execute
        result = await _process_message_async(
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
            auto_apply=True,
            timezone="UTC"
        )
        
        # Assertions
        assert result["status"] == "needs_confirmation"
        assert "proposal_id" in result
        
        # Verify proposal status was set to NEEDS_CONFIRMATION
        mock_proposal_repo.update_status.assert_any_call(
            mocks["proposal"].id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=mock_llm_response.model_dump(),
            resolution=mock_resolution.model_dump(),
        )
        
        # Verify PROPOSAL_NEEDS_CONFIRMATION event was published
        event_calls = mocks["event_bus"].return_value.publish.call_args_list
        needs_confirmation_event = None
        for call in event_calls:
            event = call[0][0]
            if event.type == EventType.PROPOSAL_NEEDS_CONFIRMATION:
                needs_confirmation_event = event
                break
        
        assert needs_confirmation_event is not None
        
        # Verify ProposalsService.apply_proposal was NOT called
        mocks["proposals_service"].return_value.apply_proposal.assert_not_called()


@pytest.mark.asyncio
async def test_empty_ops_without_confirmation_auto_apply(mock_dependencies):
    """
    Test: When LLM returns needs_confirmation=false, ops=[], auto_apply=true
    Expected: status ready with no_op flag, no task changes, no apply attempt
    """
    conversation_id = str(uuid4())
    message_id = str(uuid4())
    version = 1
    
    # Setup mocks
    mocks = mock_dependencies
    # Set mock proposal's message_id to match the test's message_id
    mocks["proposal"].message_id = UUID(message_id)
    
    # Mock proposal repository
    mock_proposal_repo = AsyncMock()
    mock_proposal_repo.list_by_conversation = AsyncMock(return_value=[mocks["proposal"]])
    mock_proposal_repo.update_status = AsyncMock()
    
    # Mock other repositories
    mock_message = _create_mock_message()
    mock_message_repo = AsyncMock()
    mock_message_repo.get_by_id = AsyncMock(return_value=mock_message)
    mock_message_repo.get_recent_context = AsyncMock(return_value=[])
    
    mock_conversation = _create_mock_conversation()
    mock_conversation_repo = AsyncMock()
    mock_conversation_repo.get_version = AsyncMock(return_value=version)
    mock_conversation_repo.get_by_id = AsyncMock(return_value=mock_conversation)
    
    mock_task_repo = AsyncMock()
    mock_task_repo.get_active_snapshot = AsyncMock(return_value=[])
    
    # Patch repository constructors
    with patch("app.workers.tasks.ProposalRepository", return_value=mock_proposal_repo), \
         patch("app.workers.tasks.MessageRepository", return_value=mock_message_repo), \
         patch("app.workers.tasks.ConversationRepository", return_value=mock_conversation_repo), \
         patch("app.workers.tasks.TaskRepository", return_value=mock_task_repo):
        
        # LLM returns empty ops with needs_confirmation=false
        mock_llm_response = LlmProposalPayload(
            ops=[],
            needs_confirmation=False,
            reasoning="No actionable tasks in message"
        )
        mocks["llm_provider"].return_value.generate_proposal = AsyncMock(
            return_value=mock_llm_response
        )
        
        # Resolver returns no resolutions
        mock_resolution = ProposalResolution(
            resolutions=[],
            needs_confirmation=False
        )
        mocks["resolver_service"].return_value.resolve_operations = AsyncMock(
            return_value=mock_resolution
        )
        
        # Execute
        result = await _process_message_async(
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
            auto_apply=True,
            timezone="UTC"
        )
        
        # Assertions
        assert result["status"] == "ready"
        assert result.get("no_op") is True
        assert "proposal_id" in result
        
        # Verify proposal status was set to READY
        mock_proposal_repo.update_status.assert_any_call(
            mocks["proposal"].id,
            ProposalStatus.READY.value,
            ops=mock_llm_response.model_dump(),
            resolution=mock_resolution.model_dump(),
        )
        
        # Verify PROPOSAL_READY event was published with no_op flag
        event_calls = mocks["event_bus"].return_value.publish.call_args_list
        ready_event = None
        for call in event_calls:
            event = call[0][0]
            if event.type == EventType.PROPOSAL_READY:
                ready_event = event
                break
        
        assert ready_event is not None
        assert ready_event.data.get("no_op") is True
        
        # Verify ProposalsService.apply_proposal was NOT called
        mocks["proposals_service"].return_value.apply_proposal.assert_not_called()


@pytest.mark.asyncio
async def test_valid_ops_needs_confirmation_false_auto_apply(mock_dependencies):
    """
    Test: When LLM returns needs_confirmation=false with valid ops, auto_apply=true
    Expected: status applied, tasks affected > 0, PROPOSAL_APPLIED event emitted
    """
    conversation_id = str(uuid4())
    message_id = str(uuid4())
    version = 1
    
    # Setup mocks
    mocks = mock_dependencies
    # Set mock proposal's message_id to match the test's message_id
    mocks["proposal"].message_id = UUID(message_id)
    
    # Mock proposal repository
    mock_proposal_repo = AsyncMock()
    mock_proposal_repo.list_by_conversation = AsyncMock(return_value=[mocks["proposal"]])
    mock_proposal_repo.update_status = AsyncMock()
    
    # Mock other repositories
    mock_message = _create_mock_message()
    mock_message_repo = AsyncMock()
    mock_message_repo.get_by_id = AsyncMock(return_value=mock_message)
    mock_message_repo.get_recent_context = AsyncMock(return_value=[])
    
    mock_conversation = _create_mock_conversation()
    mock_conversation_repo = AsyncMock()
    mock_conversation_repo.get_version = AsyncMock(return_value=version)
    mock_conversation_repo.get_by_id = AsyncMock(return_value=mock_conversation)
    
    mock_task_repo = AsyncMock()
    mock_task_repo.get_active_snapshot = AsyncMock(return_value=[])
    
    # Patch repository constructors
    with patch("app.workers.tasks.ProposalRepository", return_value=mock_proposal_repo), \
         patch("app.workers.tasks.MessageRepository", return_value=mock_message_repo), \
         patch("app.workers.tasks.ConversationRepository", return_value=mock_conversation_repo), \
         patch("app.workers.tasks.TaskRepository", return_value=mock_task_repo):
        
        # LLM returns valid ops with needs_confirmation=false
        mock_llm_response = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.CREATE,
                    temp_id="task_1",
                    title="Test task",
                    description="A test task",
                )
            ],
            needs_confirmation=False,
            reasoning="Clear task creation request"
        )
        mocks["llm_provider"].return_value.generate_proposal = AsyncMock(
            return_value=mock_llm_response
        )
        
        # Resolver returns no resolutions (no refs to resolve)
        mock_resolution = ProposalResolution(
            resolutions=[],
            needs_confirmation=False
        )
        mocks["resolver_service"].return_value.resolve_operations = AsyncMock(
            return_value=mock_resolution
        )
        
        # Mock apply_proposal result
        from app.schemas.proposals import ApplyProposalResponse
        mocks["proposals_service"].return_value.apply_proposal = AsyncMock(
            return_value=ApplyProposalResponse(
                proposal_id=mocks["proposal"].id,
                status=ProposalStatus.APPLIED,
                tasks_affected=1
            )
        )
        
        # Execute
        result = await _process_message_async(
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
            auto_apply=True,
            timezone="UTC"
        )
        
        # Assertions
        assert result["status"] == "applied"
        assert result["tasks_affected"] == 1
        assert "proposal_id" in result
        
        # Verify proposal status was first set to READY
        mock_proposal_repo.update_status.assert_any_call(
            mocks["proposal"].id,
            ProposalStatus.READY.value,
            ops=mock_llm_response.model_dump(),
            resolution=mock_resolution.model_dump(),
        )
        
        # Verify apply_proposal was called
        mocks["proposals_service"].return_value.apply_proposal.assert_called_once()


@pytest.mark.asyncio
async def test_resolver_needs_confirmation_overrides_llm(mock_dependencies):
    """
    Test: When LLM returns needs_confirmation=false but resolver returns needs_confirmation=true
    Expected: status must be needs_confirmation (resolver overrides)
    """
    conversation_id = str(uuid4())
    message_id = str(uuid4())
    version = 1
    
    # Setup mocks
    mocks = mock_dependencies
    # Set mock proposal's message_id to match the test's message_id
    mocks["proposal"].message_id = UUID(message_id)
    
    # Mock proposal repository
    mock_proposal_repo = AsyncMock()
    mock_proposal_repo.list_by_conversation = AsyncMock(return_value=[mocks["proposal"]])
    mock_proposal_repo.update_status = AsyncMock()
    
    # Mock other repositories
    mock_message = _create_mock_message()
    mock_message_repo = AsyncMock()
    mock_message_repo.get_by_id = AsyncMock(return_value=mock_message)
    mock_message_repo.get_recent_context = AsyncMock(return_value=[])
    
    mock_conversation = _create_mock_conversation()
    mock_conversation_repo = AsyncMock()
    mock_conversation_repo.get_version = AsyncMock(return_value=version)
    mock_conversation_repo.get_by_id = AsyncMock(return_value=mock_conversation)
    
    mock_task_repo = AsyncMock()
    mock_task_repo.get_active_snapshot = AsyncMock(return_value=[])
    
    # Patch repository constructors
    with patch("app.workers.tasks.ProposalRepository", return_value=mock_proposal_repo), \
         patch("app.workers.tasks.MessageRepository", return_value=mock_message_repo), \
         patch("app.workers.tasks.ConversationRepository", return_value=mock_conversation_repo), \
         patch("app.workers.tasks.TaskRepository", return_value=mock_task_repo):
        
        # LLM returns ops with needs_confirmation=false
        from app.schemas.proposals import TaskRef
        from app.schemas.enums import TaskRefType
        
        mock_llm_response = LlmProposalPayload(
            ops=[
                TaskOp(
                    op=OpType.UPDATE,
                    ref=TaskRef(type=TaskRefType.NATURAL, value="the meeting"),
                    title="Updated meeting title",
                )
            ],
            needs_confirmation=False,
            reasoning="Update requested"
        )
        mocks["llm_provider"].return_value.generate_proposal = AsyncMock(
            return_value=mock_llm_response
        )
        
        # Resolver finds ambiguous reference and requires confirmation
        mock_resolution = ProposalResolution(
            resolutions=[
                TaskResolution(
                    ref=TaskRef(type=TaskRefType.NATURAL, value="the meeting"),
                    resolved_task_id=None,
                    confidence=0.5,
                    candidates=[],
                    requires_confirmation=True
                )
            ],
            needs_confirmation=True  # Aggregated flag set to true
        )
        mocks["resolver_service"].return_value.resolve_operations = AsyncMock(
            return_value=mock_resolution
        )
        
        # Execute
        result = await _process_message_async(
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
            auto_apply=True,
            timezone="UTC"
        )
        
        # Assertions
        assert result["status"] == "needs_confirmation"
        
        # Verify proposal status was set to NEEDS_CONFIRMATION
        mock_proposal_repo.update_status.assert_any_call(
            mocks["proposal"].id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=mock_llm_response.model_dump(),
            resolution=mock_resolution.model_dump(),
        )
        
        # Verify apply_proposal was NOT called despite auto_apply=true
        mocks["proposals_service"].return_value.apply_proposal.assert_not_called()


@pytest.mark.asyncio
async def test_apply_proposal_with_empty_ops_returns_ready():
    """
    Test ProposalsService.apply_proposal with empty ops
    Expected: Returns READY status with 0 tasks affected, does not mark as APPLIED
    """
    from app.services.proposals_service import ProposalsService
    from app.schemas.proposals import ApplyProposalRequest
    
    mock_session = AsyncMock()
    
    # Mock proposal
    proposal_id = uuid4()
    conversation_id = uuid4()
    mock_proposal = MagicMock()
    mock_proposal.id = proposal_id
    mock_proposal.conversation_id = conversation_id
    mock_proposal.status = ProposalStatus.READY.value
    mock_proposal.version = 1
    mock_proposal.ops = {
        "ops": [],
        "needs_confirmation": False,
        "reasoning": "No operations"
    }
    
    # Mock repositories
    mock_proposal_repo = AsyncMock()
    mock_proposal_repo.get_by_id = AsyncMock(return_value=mock_proposal)
    mock_proposal_repo.update_status = AsyncMock()
    
    mock_conversation_repo = AsyncMock()
    mock_conversation_repo.get_version = AsyncMock(return_value=1)
    
    with patch("app.services.proposals_service.ProposalRepository", return_value=mock_proposal_repo), \
         patch("app.services.proposals_service.ConversationRepository", return_value=mock_conversation_repo), \
         patch("app.services.proposals_service.get_event_bus") as mock_event_bus:
        
        mock_event_bus.return_value.publish = AsyncMock()
        
        service = ProposalsService(mock_session)
        service.proposal_repo = mock_proposal_repo
        service.conversation_repo = mock_conversation_repo
        
        # Execute
        result = await service.apply_proposal(
            ApplyProposalRequest(proposal_id=proposal_id)
        )
        
        # Assertions
        assert result.status == ProposalStatus.READY
        assert result.tasks_affected == 0
        
        # Verify update_status was NOT called (status remains READY)
        mock_proposal_repo.update_status.assert_not_called()
        
        # Verify no events were published
        mock_event_bus.return_value.publish.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
