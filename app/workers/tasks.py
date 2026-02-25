"""Refactored Celery tasks for background processing.

This module replaces the original tasks.py with a clean, SOLID-compliant architecture.
The God Function has been replaced with a modular, service-based design.

Architecture:
- MessageProcessor: Main orchestrator
- ContextLoader: Loads all context data
- IntentStrategyHandler: Handles pre-classified intents
- EventNotifier: Publishes WebSocket events
- ProposalStatusManager: Manages proposal persistence
- ProposalEnricher: Enriches proposals with clarifications

The Celery task entry point is now a thin wrapper that delegates to MessageProcessor.
"""

import asyncio
from typing import Any
from uuid import UUID

import structlog

from app.db.session import get_session_factory
from app.events.bus import get_event_bus
from app.workers.celery_app import celery_app
from app.workers.event_notifier import EventNotifier
from app.workers.message_processor import MessageProcessor

logger = structlog.get_logger(__name__)


def _get_or_create_event_loop():
    """Get or create event loop for async operations."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


@celery_app.task(name="app.workers.tasks.process_message", bind=True)
def process_message(
    self,
    conversation_id: str,
    message_id: str,
    version: int,
    auto_apply: bool = True,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """
    Process a user message and generate task proposal.

    This is a thin wrapper that delegates to MessageProcessor.
    The actual processing is done in _process_message_async.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        version: Conversation version
        auto_apply: Whether to auto-apply proposals
        timezone: User timezone

    Returns:
        Processing result dictionary
    """
    loop = _get_or_create_event_loop()
    return loop.run_until_complete(
        _process_message_async(
            conversation_id,
            message_id,
            version,
            auto_apply,
            timezone,
        )
    )


async def _process_message_async(
    conversation_id: str,
    message_id: str,
    version: int,
    auto_apply: bool,
    timezone: str,
) -> dict[str, Any]:
    """
    Async implementation of message processing.

    Delegates to MessageProcessor for all business logic.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        version: Conversation version
        auto_apply: Whether to auto-apply proposals
        timezone: User timezone

    Returns:
        Processing result dictionary
    """
    conv_id = UUID(conversation_id)
    msg_id = UUID(message_id)

    # Get event bus (already initialized at worker startup)
    event_bus = get_event_bus()

    # Get database session
    session_factory = get_session_factory()

    async with session_factory() as session:
        # Initialize services
        event_notifier = EventNotifier(event_bus)
        processor = MessageProcessor(session, event_notifier)

        # Delegate to processor
        return await processor.process(
            conv_id,
            msg_id,
            version,
            auto_apply,
            timezone,
        )
