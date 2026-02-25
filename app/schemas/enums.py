"""Enum definitions for schemas."""

from enum import Enum


class MessageRole(str, Enum):
    """Message role enum."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ProposalStatus(str, Enum):
    """Proposal status enum."""

    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    NEEDS_CONFIRMATION = "needs_confirmation"
    APPLIED = "applied"
    STALE = "stale"
    FAILED = "failed"
    CANCELED = "canceled"


class ItemType(str, Enum):
    """Item type enum."""

    TASK = "TASK"
    NOTE = "NOTE"


class ItemStatus(str, Enum):
    """Item status enum."""

    ACTIVE = "ACTIVE"
    DONE = "DONE"
    CANCELED = "CANCELED"
    ARCHIVED = "ARCHIVED"


class ItemPriority(str, Enum):
    """Item priority enum."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class OpType(str, Enum):
    """Operation type enum."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CANCEL = "cancel"
    DONE = "done"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    PIN = "pin"
    UNPIN = "unpin"


class ItemRefType(str, Enum):
    """Item reference type enum."""

    ITEM_ID = "item_id"
    TEMP_ID = "temp_id"
    NATURAL = "natural"


class EventType(str, Enum):
    """WebSocket event type enum."""

    MESSAGE_RECEIVED = "message.received"
    LLM_QUEUED = "llm.queued"
    LLM_RUNNING = "llm.running"
    PROPOSAL_READY = "proposal.ready"
    PROPOSAL_NEEDS_CONFIRMATION = "proposal.needs_confirmation"
    PROPOSAL_APPLIED = "proposal.applied"
    PROPOSAL_STALE = "proposal.stale"
    PROPOSAL_FAILED = "proposal.failed"
    PROPOSAL_CANCELED = "proposal.canceled"
    PROPOSAL_APPROVED = "proposal.approved"
    ITEMS_CHANGED = "items.changed"


class ItemEventType(str, Enum):
    """Item event type enum."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    CANCELED = "CANCELED"
    DONE = "DONE"
    RESCHEDULED = "RESCHEDULED"
    ARCHIVED = "ARCHIVED"
    UNARCHIVED = "UNARCHIVED"
    PINNED = "PINNED"
    UNPINNED = "UNPINNED"


class ClarificationField(str, Enum):
    """Clarification field type enum."""

    DUE_AT = "due_at"
    CONFLICT = "conflict"


class ConfirmAction(str, Enum):
    """Confirm action enum."""

    APPLY = "apply"
    REPLACE_EXISTING = "replace_existing"
    RESCHEDULE_NEW = "reschedule_new"
    CANCEL_NEW = "cancel_new"


# Legacy aliases for backward compatibility during migration
TaskStatus = ItemStatus
TaskPriority = ItemPriority
TaskRefType = ItemRefType
TaskEventType = ItemEventType
