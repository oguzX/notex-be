"""Tests for message idempotency."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

from app.schemas.messages import MessageCreate, MessageEnqueuedResponse
from app.services.messages_service import MessagesService


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_message_repo():
    """Create a mock message repository."""
    return AsyncMock()


@pytest.fixture
def mock_conversation_repo():
    """Create a mock conversation repository."""
    return AsyncMock()


@pytest.fixture
def mock_proposal_repo():
    """Create a mock proposal repository."""
    return AsyncMock()


class TestMessageIdempotency:
    """Tests for message creation idempotency."""

    @pytest.mark.asyncio
    async def test_new_message_without_client_message_id(
        self,
        mock_session,
        mock_message_repo,
        mock_conversation_repo,
        mock_proposal_repo,
    ):
        """Test creating a new message without client_message_id."""
        conversation_id = uuid4()
        message_id = uuid4()
        proposal_id = uuid4()
        version = 5

        # Setup mocks
        mock_conversation_repo.increment_version = AsyncMock(return_value=version)
        
        mock_message = MagicMock()
        mock_message.id = message_id
        mock_message_repo.create = AsyncMock(return_value=mock_message)
        
        mock_proposal = MagicMock()
        mock_proposal.id = proposal_id
        mock_proposal_repo.create = AsyncMock(return_value=mock_proposal)

        with patch("app.services.messages_service.MessageRepository", return_value=mock_message_repo), \
             patch("app.services.messages_service.ConversationRepository", return_value=mock_conversation_repo), \
             patch("app.services.messages_service.ProposalRepository", return_value=mock_proposal_repo), \
             patch("app.services.messages_service.get_event_bus") as mock_event_bus, \
             patch("app.services.messages_service.get_celery_app") as mock_celery:
            
            mock_event_bus.return_value.publish = AsyncMock()
            mock_celery.return_value.send_task = MagicMock()

            service = MessagesService(mock_session)
            
            data = MessageCreate(
                content="Test message",
                timezone="UTC",
                auto_apply=True,
            )
            
            result = await service.create_message(conversation_id, data)
            
            # Verify new message was created
            assert result.message_id == message_id
            assert result.conversation_id == conversation_id
            assert result.version == version
            assert result.enqueued is True
            
            # Verify version was incremented
            mock_conversation_repo.increment_version.assert_called_once_with(conversation_id)
            
            # Verify message was created
            mock_message_repo.create.assert_called_once()
            
            # Verify Celery task was enqueued
            mock_celery.return_value.send_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_message_with_client_message_id(
        self,
        mock_session,
        mock_message_repo,
        mock_conversation_repo,
        mock_proposal_repo,
    ):
        """Test creating a new message with client_message_id (first time)."""
        conversation_id = uuid4()
        message_id = uuid4()
        proposal_id = uuid4()
        client_message_id = "client-msg-123"
        version = 5

        # Setup mocks - no existing message found
        mock_message_repo.get_by_client_message_id = AsyncMock(return_value=None)
        mock_conversation_repo.increment_version = AsyncMock(return_value=version)
        
        mock_message = MagicMock()
        mock_message.id = message_id
        mock_message_repo.create = AsyncMock(return_value=mock_message)
        
        mock_proposal = MagicMock()
        mock_proposal.id = proposal_id
        mock_proposal_repo.create = AsyncMock(return_value=mock_proposal)

        with patch("app.services.messages_service.MessageRepository", return_value=mock_message_repo), \
             patch("app.services.messages_service.ConversationRepository", return_value=mock_conversation_repo), \
             patch("app.services.messages_service.ProposalRepository", return_value=mock_proposal_repo), \
             patch("app.services.messages_service.get_event_bus") as mock_event_bus, \
             patch("app.services.messages_service.get_celery_app") as mock_celery:
            
            mock_event_bus.return_value.publish = AsyncMock()
            mock_celery.return_value.send_task = MagicMock()

            service = MessagesService(mock_session)
            
            data = MessageCreate(
                content="Test message",
                client_message_id=client_message_id,
                timezone="UTC",
                auto_apply=True,
            )
            
            result = await service.create_message(conversation_id, data)
            
            # Verify new message was created
            assert result.message_id == message_id
            assert result.enqueued is True
            
            # Verify idempotency check was performed
            mock_message_repo.get_by_client_message_id.assert_called_once_with(
                conversation_id, client_message_id
            )
            
            # Verify new message was created
            mock_message_repo.create.assert_called_once()
            
            # Verify Celery task was enqueued
            mock_celery.return_value.send_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_client_message_id_returns_existing(
        self,
        mock_session,
        mock_message_repo,
        mock_conversation_repo,
        mock_proposal_repo,
    ):
        """Test that duplicate client_message_id returns existing message."""
        conversation_id = uuid4()
        existing_message_id = uuid4()
        client_message_id = "client-msg-123"
        current_version = 10

        # Setup mocks - existing message found
        existing_message = MagicMock()
        existing_message.id = existing_message_id
        mock_message_repo.get_by_client_message_id = AsyncMock(return_value=existing_message)
        mock_conversation_repo.get_version = AsyncMock(return_value=current_version)

        with patch("app.services.messages_service.MessageRepository", return_value=mock_message_repo), \
             patch("app.services.messages_service.ConversationRepository", return_value=mock_conversation_repo), \
             patch("app.services.messages_service.ProposalRepository", return_value=mock_proposal_repo), \
             patch("app.services.messages_service.get_event_bus") as mock_event_bus, \
             patch("app.services.messages_service.get_celery_app") as mock_celery:
            
            mock_event_bus.return_value.publish = AsyncMock()
            mock_celery.return_value.send_task = MagicMock()

            service = MessagesService(mock_session)
            
            data = MessageCreate(
                content="Test message",
                client_message_id=client_message_id,
                timezone="UTC",
                auto_apply=True,
            )
            
            result = await service.create_message(conversation_id, data)
            
            # Verify existing message was returned
            assert result.message_id == existing_message_id
            assert result.conversation_id == conversation_id
            assert result.version == current_version
            assert result.enqueued is False  # Not newly enqueued
            
            # Verify idempotency check was performed
            mock_message_repo.get_by_client_message_id.assert_called_once_with(
                conversation_id, client_message_id
            )
            
            # Verify NO new message was created
            mock_message_repo.create.assert_not_called()
            
            # Verify NO version increment
            mock_conversation_repo.increment_version.assert_not_called()
            
            # Verify NO Celery task was enqueued
            mock_celery.return_value.send_task.assert_not_called()
            
            # Verify NO events were published
            mock_event_bus.return_value.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_client_message_ids_create_separate_messages(
        self,
        mock_session,
        mock_message_repo,
        mock_conversation_repo,
        mock_proposal_repo,
    ):
        """Test that different client_message_ids create separate messages."""
        conversation_id = uuid4()
        message_id_1 = uuid4()
        message_id_2 = uuid4()
        proposal_id = uuid4()

        call_count = 0
        
        def create_message_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.id = message_id_1 if call_count == 1 else message_id_2
            return mock

        # Setup mocks - no existing messages
        mock_message_repo.get_by_client_message_id = AsyncMock(return_value=None)
        mock_conversation_repo.increment_version = AsyncMock(side_effect=[5, 6])
        mock_message_repo.create = AsyncMock(side_effect=create_message_mock)
        
        mock_proposal = MagicMock()
        mock_proposal.id = proposal_id
        mock_proposal_repo.create = AsyncMock(return_value=mock_proposal)

        with patch("app.services.messages_service.MessageRepository", return_value=mock_message_repo), \
             patch("app.services.messages_service.ConversationRepository", return_value=mock_conversation_repo), \
             patch("app.services.messages_service.ProposalRepository", return_value=mock_proposal_repo), \
             patch("app.services.messages_service.get_event_bus") as mock_event_bus, \
             patch("app.services.messages_service.get_celery_app") as mock_celery:
            
            mock_event_bus.return_value.publish = AsyncMock()
            mock_celery.return_value.send_task = MagicMock()

            service = MessagesService(mock_session)
            
            # First message
            data1 = MessageCreate(
                content="First message",
                client_message_id="client-msg-001",
                timezone="UTC",
                auto_apply=True,
            )
            result1 = await service.create_message(conversation_id, data1)
            
            # Second message with different client_message_id
            data2 = MessageCreate(
                content="Second message",
                client_message_id="client-msg-002",
                timezone="UTC",
                auto_apply=True,
            )
            result2 = await service.create_message(conversation_id, data2)
            
            # Verify both messages were created
            assert result1.message_id == message_id_1
            assert result2.message_id == message_id_2
            assert result1.enqueued is True
            assert result2.enqueued is True
            
            # Verify both created new messages
            assert mock_message_repo.create.call_count == 2
            assert mock_celery.return_value.send_task.call_count == 2
