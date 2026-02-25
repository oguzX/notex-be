"""Message processing context data container."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.db.models.proposal import Proposal
from app.db.models.user import User


@dataclass(frozen=True)
class MessageContext:
    """
    Immutable data container for message processing context.

    Contains all the necessary data loaded at the start of processing,
    preventing repeated database queries and ensuring consistency.
    """

    conversation_id: UUID
    message_id: UUID
    version: int
    auto_apply: bool
    timezone: str

    # Database entities
    message: Message
    conversation: Conversation
    proposal: Proposal
    user: User | None

    # Computed values
    reference_dt_utc: datetime

    @property
    def user_timezone(self) -> str:
        """Get user's preferred timezone, falling back to provided timezone."""
        if self.user and self.user.timezone:
            return self.user.timezone
        return self.timezone
