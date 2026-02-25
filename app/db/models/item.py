"""Item model - unified entity for tasks and notes."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Item(Base):
    """
    Unified Item model representing both tasks and notes.
    
    Discriminated by `type` column:
    - TASK: Has due_at, can be ACTIVE/DONE/CANCELED
    - NOTE: No due_at, can be ACTIVE/ARCHIVED, supports pinned
    """

    __tablename__ = "items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # TASK, NOTE
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="MEDIUM"
    )  # LOW, MEDIUM, HIGH, URGENT
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="GENERAL"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE"
    )  # ACTIVE, DONE, CANCELED, ARCHIVED
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_message_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="items"
    )
    user: Mapped["User"] = relationship("User", back_populates="items")
    events: Mapped[list["ItemEvent"]] = relationship(
        "ItemEvent", back_populates="item", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Item(id={self.id}, type={self.type}, title={self.title[:30]}, status={self.status})>"

    @property
    def is_task(self) -> bool:
        """Check if this item is a task."""
        return self.type == "TASK"

    @property
    def is_note(self) -> bool:
        """Check if this item is a note."""
        return self.type == "NOTE"
