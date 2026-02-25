"""Intent dispatcher – routes LLM classification results to domain services."""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    NoApprovableProposalError,
    ProposalAlreadyProcessedError,
    ProposalNotFoundError,
    ProposalNotReadyError,
    StaleProposalError,
)
from app.db.repositories.proposal_repo import ProposalRepository
from app.events.bus import get_event_bus
from app.schemas.enums import EventType, ProposalStatus
from app.schemas.events import WsEvent
from app.schemas.intents import ConfirmationType, IntentClassification, UserIntent
from app.schemas.proposals import ApplyProposalRequest
from app.services.proposals_service import ProposalsService

logger = structlog.get_logger(__name__)


class IntentDispatchResult:
    """Outcome returned by the dispatcher to the worker."""

    __slots__ = ("handled", "status", "proposal_id", "items_affected", "error")

    def __init__(
        self,
        *,
        handled: bool,
        status: str,
        proposal_id: UUID | None = None,
        items_affected: int = 0,
        error: str | None = None,
    ):
        self.handled = handled
        self.status = status
        self.proposal_id = proposal_id
        self.items_affected = items_affected
        self.error = error


async def dispatch_intent(
    *,
    session: AsyncSession,
    classification: IntentClassification,
    conversation_id: UUID,
    message_id: UUID,
    version: int,
) -> IntentDispatchResult:
    """Route an LLM-classified intent to the appropriate domain action.

    Returns an ``IntentDispatchResult`` so the caller (worker task) can
    decide what events / response payload to emit.

    For ``UserIntent.OPS`` the caller should fall through to the normal
    proposal-create-and-apply pipeline – this function returns
    ``handled=False`` in that case.
    """

    if classification.intent == UserIntent.APPROVE_PROPOSAL:
        return await _handle_approve(
            session=session,
            classification=classification,
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
        )

    if classification.intent == UserIntent.CANCEL_PROPOSAL:
        return await _handle_cancel(
            session=session,
            classification=classification,
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
        )

    if classification.intent == UserIntent.NOTE_ONLY:
        # Message is already persisted by the caller; nothing else to do.
        return IntentDispatchResult(handled=True, status="note_only")

    # OPS or any unknown intent – let the normal pipeline handle it.
    return IntentDispatchResult(handled=False, status="ops_fallthrough")


# ── private handlers ────────────────────────────────────────────────


async def _handle_approve(
    *,
    session: AsyncSession,
    classification: IntentClassification,
    conversation_id: UUID,
    message_id: UUID,
    version: int,
) -> IntentDispatchResult:
    """Approve (apply) an existing proposal."""
    proposals_service = ProposalsService(session)

    try:
        result = await proposals_service.approve_proposal(
            conversation_id=conversation_id,
            proposal_id=classification.proposal_id,
        )
    except (
        ProposalNotFoundError,
        NoApprovableProposalError,
        ProposalNotReadyError,
        ProposalAlreadyProcessedError,
        StaleProposalError,
    ) as exc:
        logger.warning(
            "intent_approve_failed",
            conversation_id=str(conversation_id),
            proposal_id=str(classification.proposal_id),
            error=exc.message,
        )
        return IntentDispatchResult(
            handled=True,
            status="error",
            error=exc.message,
        )

    # Publish approval event
    event_bus = get_event_bus()
    await event_bus.publish(
        WsEvent(
            type=EventType.PROPOSAL_APPROVED,
            conversation_id=conversation_id,
            message_id=message_id,
            proposal_id=result.proposal_id,
            version=version,
            data={
                "status": result.status.value,
                "items_affected": result.items_affected,
            },
        )
    )

    return IntentDispatchResult(
        handled=True,
        status="applied",
        proposal_id=result.proposal_id,
        items_affected=result.items_affected,
    )


async def _handle_cancel(
    *,
    session: AsyncSession,
    classification: IntentClassification,
    conversation_id: UUID,
    message_id: UUID,
    version: int,
) -> IntentDispatchResult:
    """Cancel an existing proposal."""
    proposals_service = ProposalsService(session)
    proposal_repo = ProposalRepository(session)

    # Resolve the target proposal
    proposal_id = classification.proposal_id
    if proposal_id:
        proposal = await proposal_repo.get_by_id(proposal_id)
        if not proposal or proposal.conversation_id != conversation_id:
            return IntentDispatchResult(
                handled=True,
                status="error",
                error=f"Proposal {proposal_id} not found in this conversation",
            )
    else:
        proposal = await proposal_repo.get_latest_actionable(conversation_id)
        if not proposal:
            return IntentDispatchResult(
                handled=True,
                status="error",
                error="No actionable proposal to cancel",
            )

    # Only cancel if in an actionable state
    if proposal.status in (
        ProposalStatus.APPLIED.value,
        ProposalStatus.CANCELED.value,
    ):
        return IntentDispatchResult(
            handled=True,
            status="error",
            error=f"Proposal already {proposal.status}",
        )

    await proposal_repo.update_status(
        proposal.id,
        ProposalStatus.CANCELED.value,
        error_message="Canceled via user intent",
    )
    await session.commit()

    event_bus = get_event_bus()
    await event_bus.publish(
        WsEvent(
            type=EventType.PROPOSAL_CANCELED,
            conversation_id=conversation_id,
            message_id=message_id,
            proposal_id=proposal.id,
            version=version,
            data={"reason": "user_intent"},
        )
    )

    logger.info(
        "intent_cancel_applied",
        proposal_id=str(proposal.id),
        conversation_id=str(conversation_id),
    )

    return IntentDispatchResult(
        handled=True,
        status="canceled",
        proposal_id=proposal.id,
    )
