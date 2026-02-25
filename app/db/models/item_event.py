"""Item event model for audit trail."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ItemEvent(Base):
    """
    Item event model for tracking changes.
    
    Event types:
    - CREATED: Item was created
    - UPDATED: Item was updated
    - DELETED: Item was soft-deleted
    - CANCELED: Task was canceled (status change)
    - DONE: Task was marked done (status change)
    - RESCHEDULED: Task due_at was changed
    - ARCHIVED: Note was archived
    - UNARCHIVED: Note was unarchived
    - PINNED: Note was pinned
    - UNPINNED: Note was unpinned
    """

    __tablename__ = "item_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="events")
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="item_events"
    )
    proposal: Mapped["Proposal | None"] = relationship(
        "Proposal", back_populates="item_events"
    )

    def __repr__(self) -> str:
        return f"<ItemEvent(id={self.id}, event_type={self.event_type})>"
