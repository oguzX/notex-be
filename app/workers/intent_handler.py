"""Intent classification and handling strategy."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.intent_classifier import IntentType, classify_intent
from app.schemas.enums import ProposalStatus
from app.schemas.intents import IntentClassification, UserIntent
from app.services.intent_dispatcher import IntentDispatchResult, dispatch_intent
from app.workers.event_notifier import EventNotifier
from app.workers.message_context import MessageContext

logger = structlog.get_logger(__name__)


@dataclass
class IntentHandlingResult:
    """Result of intent handling."""

    handled: bool
    """Whether the intent was handled (early exit)."""

    status: str | None = None
    """Status of the handling (applied, canceled, note_only, error)."""

    proposal_id: UUID | None = None
    """Proposal ID if created."""

    items_affected: int = 0
    """Number of items affected."""

    error: str | None = None
    """Error message if handling failed."""


class IntentStrategyHandler:
    """
    Strategy handler for pre-classified intents.

    Handles simple intents that don't require LLM processing:
    - APPROVE_PROPOSAL
    - CANCEL_PROPOSAL
    - NOTE_ONLY

    Uses the Strategy pattern to delegate to appropriate handlers.
    """

    # Mapping from IntentType to UserIntent
    INTENT_MAPPING = {
        IntentType.APPROVE_PROPOSAL: UserIntent.APPROVE_PROPOSAL,
        IntentType.CANCEL_PROPOSAL: UserIntent.CANCEL_PROPOSAL,
        IntentType.NOTE_ONLY: UserIntent.NOTE_ONLY,
    }

    def __init__(
        self,
        session: AsyncSession,
        event_notifier: EventNotifier,
    ):
        """
        Initialize IntentStrategyHandler.

        Args:
            session: Database session
            event_notifier: Event notifier for publishing events
        """
        self.session = session
        self.event_notifier = event_notifier

    def classify_message(self, message_content: str) -> IntentType | None:
        """
        Classify message to detect simple intents.

        Args:
            message_content: Message content to classify

        Returns:
            IntentType if a simple intent is detected, None otherwise
        """
        intent = classify_intent(message_content)

        if intent in self.INTENT_MAPPING:
            return intent

        return None

    async def handle_intent(
        self,
        intent: IntentType,
        context: MessageContext,
    ) -> IntentHandlingResult:
        """
        Handle a pre-classified intent.

        Args:
            intent: The intent type to handle
            context: Message processing context

        Returns:
            IntentHandlingResult with handling status
        """
        if intent not in self.INTENT_MAPPING:
            return IntentHandlingResult(handled=False)

        logger.info(
            "handling_pre_classified_intent",
            intent=intent.value,
            message_id=str(context.message_id),
        )

        # Map to UserIntent
        user_intent = self.INTENT_MAPPING[intent]
        classification = IntentClassification(intent=user_intent)

        # Dispatch to intent dispatcher
        dispatch_result = await dispatch_intent(
            session=self.session,
            classification=classification,
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            version=context.version,
        )

        if not dispatch_result.handled:
            return IntentHandlingResult(handled=False)

        # Update proposal and publish events based on result
        from app.db.repositories.proposal_repo import ProposalRepository

        proposal_repo = ProposalRepository(self.session)

        if dispatch_result.status == "note_only":
            await self._handle_note_only(
                dispatch_result,
                context,
                proposal_repo,
            )
        elif dispatch_result.status == "error":
            await self._handle_error(
                dispatch_result,
                context,
                proposal_repo,
            )
        else:
            await self._handle_applied_or_canceled(
                dispatch_result,
                context,
                proposal_repo,
            )

        logger.info(
            "intent_handled",
            intent=intent.value,
            status=dispatch_result.status,
            proposal_id=str(dispatch_result.proposal_id) if dispatch_result.proposal_id else None,
        )

        return IntentHandlingResult(
            handled=True,
            status=dispatch_result.status,
            proposal_id=dispatch_result.proposal_id,
            items_affected=dispatch_result.items_affected,
            error=dispatch_result.error,
        )

    async def _handle_note_only(
        self,
        dispatch_result: IntentDispatchResult,
        context: MessageContext,
        proposal_repo: Any,
    ) -> None:
        """Handle NOTE_ONLY intent."""
        await proposal_repo.update_status(
            context.proposal.id,
            ProposalStatus.APPLIED.value,
            ops={"ops": [], "needs_confirmation": False, "reasoning": "note_only"},
        )
        await self.session.commit()

        # Build empty message_ops for note-only
        from app.schemas.events import MessageOpsPayload

        message_ops = MessageOpsPayload(
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            ops=[],
            resolution=None,
            clarifications=[],
            no_op=True,
            tool_response=None,
        )

        await self.event_notifier.notify_applied(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            items_affected=0,
            intent="note_only",
        )

    async def _handle_error(
        self,
        dispatch_result: IntentDispatchResult,
        context: MessageContext,
        proposal_repo: Any,
    ) -> None:
        """Handle error during intent dispatch."""
        await proposal_repo.update_status(
            context.proposal.id,
            ProposalStatus.FAILED.value,
            error_message=dispatch_result.error,
        )
        await self.session.commit()

        await self.event_notifier.notify_failed(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            error=dispatch_result.error or "Unknown error",
        )

    async def _handle_applied_or_canceled(
        self,
        dispatch_result: IntentDispatchResult,
        context: MessageContext,
        proposal_repo: Any,
    ) -> None:
        """Handle APPLIED or CANCELED status."""
        final_status = (
            ProposalStatus.APPLIED.value
            if dispatch_result.status == "applied"
            else ProposalStatus.CANCELED.value
        )
        await proposal_repo.update_status(context.proposal.id, final_status)
        await self.session.commit()
