"""Event notification service for WebSocket events."""

from typing import Any
from uuid import UUID

import structlog

from app.events.bus import EventBus
from app.schemas.enums import EventType
from app.schemas.events import MessageOpsPayload, WsEvent

logger = structlog.get_logger(__name__)


class EventNotifier:
    """
    Centralized service for publishing WebSocket events.

    Encapsulates the event publishing logic, providing clean,
    semantically named methods for different event types.
    """

    def __init__(self, event_bus: EventBus):
        """
        Initialize EventNotifier.

        Args:
            event_bus: The event bus for publishing events
        """
        self.event_bus = event_bus

    async def notify_running(
        self,
        conversation_id: UUID,
        message_id: UUID,
        proposal_id: UUID,
        version: int,
    ) -> None:
        """
        Publish LLM_RUNNING event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            proposal_id: Proposal ID
            version: Conversation version
        """
        await self.event_bus.publish(
            WsEvent(
                type=EventType.LLM_RUNNING,
                conversation_id=conversation_id,
                message_id=message_id,
                proposal_id=proposal_id,
                version=version,
            )
        )
        logger.info("event_published", event_type="llm_running", proposal_id=str(proposal_id))

    async def notify_failed(
        self,
        conversation_id: UUID,
        message_id: UUID,
        proposal_id: UUID,
        version: int,
        error: str,
        error_code: str | None = None,
    ) -> None:
        """
        Publish PROPOSAL_FAILED event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            proposal_id: Proposal ID
            version: Conversation version
            error: Error message
            error_code: Optional error code
        """
        data = {
            "error": error,
            "message_id": str(message_id),
            "proposal_id": str(proposal_id),
            "version": version,
        }
        if error_code:
            data["error_code"] = error_code

        await self.event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_FAILED,
                conversation_id=conversation_id,
                message_id=message_id,
                proposal_id=proposal_id,
                version=version,
                data=data,
            )
        )
        logger.error("event_published", event_type="proposal_failed", error=error, proposal_id=str(proposal_id))

    async def notify_stale(
        self,
        conversation_id: UUID,
        message_id: UUID,
        proposal_id: UUID,
        version: int,
        message_ops: MessageOpsPayload,
    ) -> None:
        """
        Publish PROPOSAL_STALE event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            proposal_id: Proposal ID
            version: Conversation version
            message_ops: Message operations payload
        """
        await self.event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_STALE,
                conversation_id=conversation_id,
                message_id=message_id,
                proposal_id=proposal_id,
                version=version,
                data={
                    "message_ops": message_ops.model_dump(mode="json"),
                },
            )
        )
        logger.warning("event_published", event_type="proposal_stale", proposal_id=str(proposal_id))

    async def notify_needs_confirmation(
        self,
        conversation_id: UUID,
        message_id: UUID,
        proposal_id: UUID,
        version: int,
        message_ops: MessageOpsPayload,
        resolution: dict[str, Any],
        clarifications: list[dict[str, Any]],
    ) -> None:
        """
        Publish PROPOSAL_NEEDS_CONFIRMATION event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            proposal_id: Proposal ID
            version: Conversation version
            message_ops: Message operations payload
            resolution: Resolution data
            clarifications: List of clarifications
        """
        await self.event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_NEEDS_CONFIRMATION,
                conversation_id=conversation_id,
                message_id=message_id,
                proposal_id=proposal_id,
                version=version,
                data={
                    "message_ops": message_ops.model_dump(mode="json"),
                    "resolution": resolution,
                    "clarifications": clarifications,
                },
            )
        )
        logger.info("event_published", event_type="proposal_needs_confirmation", proposal_id=str(proposal_id))

    async def notify_ready(
        self,
        conversation_id: UUID,
        message_id: UUID,
        proposal_id: UUID,
        version: int,
        message_ops: MessageOpsPayload,
        titles: list[str] | None = None,
        reasoning: str | None = None,
        no_op: bool = False,
        tool_response: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish PROPOSAL_READY event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            proposal_id: Proposal ID
            version: Conversation version
            message_ops: Message operations payload
            titles: Optional list of operation titles
            reasoning: Optional reasoning text
            no_op: Whether this is a no-op proposal
            tool_response: Optional tool response data
        """
        data: dict[str, Any] = {
            "message_ops": message_ops.model_dump(mode="json"),
        }

        if titles:
            data["titles"] = titles
        if reasoning:
            data["reasoning"] = reasoning
        if no_op:
            data["no_op"] = True
        if tool_response:
            data["tool_response"] = tool_response

        await self.event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_READY,
                conversation_id=conversation_id,
                message_id=message_id,
                proposal_id=proposal_id,
                version=version,
                data=data,
            )
        )
        logger.info("event_published", event_type="proposal_ready", proposal_id=str(proposal_id), no_op=no_op)

    async def notify_applied(
        self,
        conversation_id: UUID,
        message_id: UUID,
        proposal_id: UUID,
        version: int,
        message_ops: MessageOpsPayload,
        items_affected: int,
        intent: str | None = None,
    ) -> None:
        """
        Publish PROPOSAL_APPLIED event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            proposal_id: Proposal ID
            version: Conversation version
            message_ops: Message operations payload
            items_affected: Number of items affected
            intent: Optional intent type (e.g., "note_only")
        """
        data: dict[str, Any] = {
            "message_ops": message_ops.model_dump(mode="json"),
            "items_affected": items_affected,
        }

        if intent:
            data["intent"] = intent
            if intent == "note_only":
                data["no_op"] = True

        await self.event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_APPLIED,
                conversation_id=conversation_id,
                message_id=message_id,
                proposal_id=proposal_id,
                version=version,
                data=data,
            )
        )
        logger.info("event_published", event_type="proposal_applied", proposal_id=str(proposal_id), items_affected=items_affected)
