"""Proposal endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.core.errors import ProposalNotFoundError
from app.db.models.user import User
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.db.session import get_session
from app.schemas.proposals import (
    ApplyProposalRequest,
    ApplyProposalResponse,
    ConfirmRequest,
    ConfirmResponse,
    ConfirmTimeRequest,
    ConfirmTimeResponse,
    ProposalResponse,
)
from app.services.proposals_service import ProposalsService

router = APIRouter()


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProposalResponse:
    """Get a proposal by ID."""
    service = ProposalsService(session)
    proposal = await service.get_proposal(proposal_id)
    
    if not proposal:
        raise ProposalNotFoundError(str(proposal_id))
    
    # Verify ownership through conversation
    proposal_repo = ProposalRepository(session)
    proposal_model = await proposal_repo.get_by_id(proposal_id)
    if proposal_model:
        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.get_by_id_and_user(
            proposal_model.conversation_id, current_user.id
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
    
    return proposal


@router.get("/conversations/{conversation_id}/proposals")
async def list_proposals(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProposalResponse]:
    """List proposals for a conversation."""
    # Verify conversation ownership
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_id_and_user(
        conversation_id, current_user.id
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation not found or access denied",
        )
    
    service = ProposalsService(session)
    return await service.list_proposals(conversation_id)


@router.post("/proposals/apply", status_code=status.HTTP_200_OK)
async def apply_proposal(
    request: ApplyProposalRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApplyProposalResponse:
    """
    Manually apply a proposal.
    
    Used when auto_apply=false or confirmation is required.
    
    Optional: Pass force_item_type to override the item type (e.g., create a TASK as a NOTE).
    Example request:
    {
        "proposal_id": "...",
        "force_item_type": "NOTE"
    }
    """
    # Verify ownership through proposal's conversation
    proposal_repo = ProposalRepository(session)
    proposal = await proposal_repo.get_by_id(request.proposal_id)
    if not proposal:
        raise ProposalNotFoundError(str(request.proposal_id))
    
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_id_and_user(
        proposal.conversation_id, current_user.id
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    service = ProposalsService(session)
    return await service.apply_proposal(request)


# @router.post("/proposals/{proposal_id}/confirm-time", status_code=status.HTTP_200_OK)
# async def confirm_time(
#     proposal_id: UUID,
#     request: ConfirmTimeRequest,
#     current_user: User = Depends(get_current_user),
#     session: AsyncSession = Depends(get_session),
# ) -> ConfirmTimeResponse:
#     """
#     Confirm time for a proposal that requires time clarification.
    
#     Used when a proposal has needs_confirmation status due to missing due_at.
#     Applies the provided time updates and then applies the proposal.
#     """
#     # Verify ownership through proposal's conversation
#     proposal_repo = ProposalRepository(session)
#     proposal = await proposal_repo.get_by_id(proposal_id)
#     if not proposal:
#         raise ProposalNotFoundError(str(proposal_id))
    
#     conversation_repo = ConversationRepository(session)
#     conversation = await conversation_repo.get_by_id_and_user(
#         proposal.conversation_id, current_user.id
#     )
#     if not conversation:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Access denied",
#         )
    
#     service = ProposalsService(session)
#     result = await service.confirm_time(proposal_id, request.updates)
    
#     return ConfirmTimeResponse(
#         proposal_id=result["proposal_id"],
#         applied=result["applied"],
#         items_affected=result["items_affected"],
#     )


@router.post("/proposals/{proposal_id}/confirm", status_code=status.HTTP_200_OK)
async def confirm_proposal(
    proposal_id: UUID,
    request: ConfirmRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConfirmResponse:
    """
    Confirm a proposal with time updates or conflict resolution.
    
    This is the primary confirmation endpoint that handles:
    - action="apply": Fill in due_at and apply if no conflicts
    - action="replace_existing": Cancel conflicting task and create new one
    - action="reschedule_new": Set new time and re-check for conflicts
    - action="cancel_new": Cancel the proposal without creating new task
    
    Request body:
    {
        "updates": [
            {
                "clarification_id": "<id-from-clarifications>",
                "due_at": "2026-01-29T18:00:00Z",  // optional for reschedule
                "timezone": "UTC"
            }
        ],
        "action": "apply" | "replace_existing" | "reschedule_new" | "cancel_new"
    }
    
    Response includes:
    - applied: Whether proposal was successfully applied
    - tasks_affected: Number of tasks created/updated
    - tasks_canceled: Number of existing tasks canceled (for replace_existing)
    - needs_further_confirmation: Whether another conflict was found
    - clarifications: New clarifications if needs_further_confirmation=true
    """
    # Verify ownership through proposal's conversation
    proposal_repo = ProposalRepository(session)
    proposal = await proposal_repo.get_by_id(proposal_id)
    if not proposal:
        raise ProposalNotFoundError(str(proposal_id))
    
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_id_and_user(
        proposal.conversation_id, current_user.id
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    service = ProposalsService(session)
    return await service.confirm_proposal(
        proposal_id, request, current_user.id
    )
