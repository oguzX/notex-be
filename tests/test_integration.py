"""Integration test for message to proposal flow."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.proposal_repo import ProposalRepository


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient):
    """Test creating a conversation."""
    user_id = str(uuid4())
    
    response = await client.post(
        "/v1/conversations",
        json={"user_id": user_id, "title": "Test Conversation"},
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["user_id"] == user_id
    assert data["version"] == 0


@pytest.mark.asyncio
async def test_send_message(client: AsyncClient, test_session: AsyncSession):
    """Test sending a message and enqueueing processing."""
    # Create conversation
    conv_repo = ConversationRepository(test_session)
    conversation = await conv_repo.create(user_id=uuid4())
    await test_session.commit()
    
    # Send message
    response = await client.post(
        f"/v1/conversations/{conversation.id}/messages",
        json={
            "content": "I have a meeting at 8pm",
            "auto_apply": False,
        },
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["conversation_id"] == str(conversation.id)
    assert data["version"] == 1
    assert data["enqueued"] is True


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient, test_session: AsyncSession):
    """Test listing tasks for a conversation."""
    # Create conversation
    conv_repo = ConversationRepository(test_session)
    conversation = await conv_repo.create(user_id=uuid4())
    await test_session.commit()
    
    # List tasks
    response = await client.get(f"/v1/conversations/{conversation.id}/tasks")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_proposal(client: AsyncClient, test_session: AsyncSession):
    """Test getting a proposal."""
    # Create conversation and proposal
    conv_repo = ConversationRepository(test_session)
    conversation = await conv_repo.create(user_id=uuid4())
    
    from app.db.repositories.message_repo import MessageRepository
    
    msg_repo = MessageRepository(test_session)
    message = await msg_repo.create(
        conversation_id=conversation.id,
        role="user",
        content="test",
    )
    
    proposal_repo = ProposalRepository(test_session)
    proposal = await proposal_repo.create(
        conversation_id=conversation.id,
        message_id=message.id,
        version=1,
    )
    await test_session.commit()
    
    # Get proposal
    response = await client.get(f"/v1/proposals/{proposal.id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(proposal.id)
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health check endpoint."""
    response = await client.get("/healthz")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
