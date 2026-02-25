"""Intent classification schemas returned by the LLM pipeline."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class UserIntent(str, Enum):
    """High-level intent classification for a user message."""

    APPROVE_PROPOSAL = "approve_proposal"
    CANCEL_PROPOSAL = "cancel_proposal"
    NOTE_ONLY = "note_only"
    OPS = "ops"  # standard create/update/delete task flow


class ConfirmationType(str, Enum):
    """Sub-classification for approval intents."""

    APPLY = "apply"
    REPLACE_EXISTING = "replace_existing"


class IntentClassification(BaseModel):
    """Structured result of the LLM intent classification step.

    The LLM returns this alongside (or instead of) a normal proposal
    payload.  The worker inspects it before deciding which domain path
    to follow.
    """

    intent: UserIntent
    proposal_id: UUID | None = None
    confirmation_type: ConfirmationType | None = None


# ── Router Agent Schemas ──────────────────────────────────────────────


class RouterDecisionType(str, Enum):
    """Decision types for the Intent Router Agent.

    These decisions are context-aware and consider active proposal state.
    """

    CONFIRM_PROPOSAL = "confirm_proposal"
    """User is confirming/approving an active proposal.
    Examples: 'Evet', 'Onaylıyorum', 'Tamam', 'Yes', 'Confirm'
    Only valid when an active proposal exists with status='needs_confirmation'.
    """

    REJECT_PROPOSAL = "reject_proposal"
    """User is rejecting/canceling an active proposal.
    Examples: 'Hayır', 'İptal', 'Vazgeç', 'No', 'Cancel'
    Only valid when an active proposal exists with status='needs_confirmation'.
    """

    MODIFY_PROPOSAL = "modify_proposal"
    """User wants to modify an active proposal.
    Examples: 'Saati 5 yap', 'Hayır yarın olsun', 'Change time to 5pm'
    Only valid when an active proposal exists with status='needs_confirmation'.
    The suggested_modification field contains the user's modification request.
    """
    CREATE_TASK_OR_NOTE = "create_task_or_note"  # "Annemi ara", "Not al"
    
    TOOL_QUERY = "tool_query"

    CHITCHAT = "chitchat"
    """User is engaging in casual conversation.
    Examples: 'Selam', 'Naber', 'Hello', 'How are you'
    No task operations needed, just conversational response.
    """


class RouterDecision(BaseModel):
    """LLM-generated decision from the Intent Router Agent.

    This decision is context-aware and considers whether an active proposal
    exists. The router should only return CONFIRM/REJECT/MODIFY if there is
    an active proposal with status='needs_confirmation'.
    """

    decision: RouterDecisionType = Field(
        ...,
        description="The routing decision based on user message and context"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for this decision (0.0 to 1.0)"
    )

    reasoning: str = Field(
        ...,
        description="Brief explanation of why this decision was made"
    )

    suggested_modification: str | None = Field(
        default=None,
        description="If decision is MODIFY_PROPOSAL, this contains the user's modification request"
    )
