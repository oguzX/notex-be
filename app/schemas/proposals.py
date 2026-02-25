"""Proposal schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import (
    ClarificationField,
    ConfirmAction,
    ItemRefType,
    ItemStatus,
    ItemType,
    OpType,
    ProposalStatus,
)
from app.utils.ids import generate_clarification_id


class ItemRef(BaseModel):
    """Reference to an item in an operation."""

    type: ItemRefType
    value: str  # item_id, temp_id, or natural language description
    confidence: float | None = None


class UpcomingItemSummary(BaseModel):
    """Summary of an upcoming item for context."""

    item_id: UUID
    conversation_id: UUID
    title: str
    item_type: ItemType
    due_at: datetime | None = None
    timezone: str | None = None
    status: ItemStatus


class ClarificationContext(BaseModel):
    """Context information for clarifications."""

    upcoming_items: list[UpcomingItemSummary] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None


class ConflictInfo(BaseModel):
    """Information about a scheduling conflict."""

    existing_item: UpcomingItemSummary
    proposed_due_at: datetime
    window_minutes: int = 30


class TimeSuggestion(BaseModel):
    """Suggested time for task confirmation."""

    due_at: datetime
    timezone: str
    label: str  # e.g., "This evening (suggested)"
    confidence: float = Field(ge=0.0, le=1.0)  # 0..1


class Clarification(BaseModel):
    """Clarification request for missing information or conflicts."""

    clarification_id: str = Field(default_factory=generate_clarification_id)
    field: ClarificationField
    target_temp_id: str | None = None  # For linking to create ops
    message: str  # User-facing message
    suggestions: list[TimeSuggestion] = Field(default_factory=list)
    context: ClarificationContext | None = None
    conflict: ConflictInfo | None = None
    available_actions: list[str] = Field(default_factory=list)
    # Deprecated: op_ref - use target_temp_id instead
    op_ref: ItemRef | None = None


class ItemOp(BaseModel):
    """Single item operation."""

    op: OpType
    item_type: ItemType | None = None  # Required for create ops
    ref: ItemRef | None = None  # For update/delete/cancel/done/archive/unarchive/pin/unpin
    temp_id: str | None = None  # For create operations
    title: str | None = None
    content: str | None = None
    due_at: str | None = None  # ISO format or natural language
    priority: str | None = None
    category: str | None = None
    pinned: bool | None = None
    tags: list[str] | None = None
    reasoning: str | None = None
    # LLM suggestions (not applied automatically)
    suggested_due_at: datetime | None = None
    suggested_timezone: str | None = None
    suggested_confidence: float | None = None


class LlmProposalPayload(BaseModel):
    """LLM-generated proposal payload."""

    ops: list[ItemOp]
    needs_confirmation: bool = False
    reasoning: str | None = None
    clarifications: list[Clarification] = Field(default_factory=list)


class ResolutionCandidate(BaseModel):
    """Candidate item for resolution."""

    item_id: UUID
    score: float
    title: str
    due_at: datetime | None


class ItemResolution(BaseModel):
    """Resolution of an item reference."""

    ref: ItemRef
    resolved_item_id: UUID | None
    confidence: float
    candidates: list[ResolutionCandidate] = Field(default_factory=list)
    requires_confirmation: bool = False


class ProposalResolution(BaseModel):
    """Complete resolution data for a proposal."""

    resolutions: list[ItemResolution]
    needs_confirmation: bool


class ProposalResponse(BaseModel):
    """Schema for proposal response."""

    id: UUID
    conversation_id: UUID
    message_id: UUID
    version: int
    status: ProposalStatus
    ops: dict | None
    resolution: dict | None
    error_message: str | None
    error_details: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplyProposalRequest(BaseModel):
    """Request to apply a proposal."""

    proposal_id: UUID
    confirmed_resolutions: dict[str, UUID] | None = None  # ref_key -> item_id
    force_item_type: ItemType | None = None  # Override the proposal's item type (e.g., create TASK as NOTE)


class ApplyProposalResponse(BaseModel):
    """Response after applying a proposal."""

    proposal_id: UUID
    status: ProposalStatus
    items_affected: int


class TimeUpdateItem(BaseModel):
    """Single time update for confirm-time endpoint (deprecated, use ConfirmUpdate)."""

    ref: ItemRef  # Reference to temp_id or natural
    due_at: datetime
    timezone: str


class ConfirmTimeRequest(BaseModel):
    """Request to confirm time for a proposal (deprecated, use ConfirmRequest)."""

    updates: list[TimeUpdateItem]


class ConfirmTimeResponse(BaseModel):
    """Response after confirming time (deprecated, use ConfirmResponse)."""

    proposal_id: UUID
    applied: bool
    items_affected: int


# New confirmation schemas

class ConfirmUpdate(BaseModel):
    """Single update for confirm endpoint using clarification_id."""

    clarification_id: str  # Reference to the clarification being resolved
    due_at: datetime | None = None  # Required for reschedule_new or due_at field
    timezone: str | None = None  # IANA timezone or "UTC"


class ConfirmRequest(BaseModel):
    """Request to confirm a proposal (time or conflict resolution)."""

    updates: list[ConfirmUpdate] = Field(default_factory=list)
    action: ConfirmAction = ConfirmAction.APPLY


class ConfirmResponse(BaseModel):
    """Response after confirming a proposal."""

    proposal_id: UUID
    status: ProposalStatus
    applied: bool
    items_affected: int
    items_canceled: int = 0
    needs_further_confirmation: bool = False
    clarifications: list[Clarification] = Field(default_factory=list)


# Legacy aliases for backward compatibility
TaskRef = ItemRef
TaskOp = ItemOp
TaskResolution = ItemResolution
UpcomingTaskSummary = UpcomingItemSummary
