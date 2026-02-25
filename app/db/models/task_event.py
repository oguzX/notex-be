"""Task event model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TaskEvent(Base):
    """Task event model for audit trail."""

    __tablename__ = "task_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # created, updated, deleted, cancelled, done
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="events")
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="task_events"
    )
    proposal: Mapped["Proposal | None"] = relationship(
        "Proposal", back_populates="task_events"
    )

    def __repr__(self) -> str:
        return f"<TaskEvent(id={self.id}, event_type={self.event_type})>"
