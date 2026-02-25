"""Proposal model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Proposal(Base):
    """Proposal model representing LLM-generated task operations."""

    __tablename__ = "proposals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued", index=True
    )  # queued, running, ready, needs_confirmation, applied, stale, failed, canceled
    ops: Mapped[dict] = mapped_column(JSONB, nullable=True)
    resolution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="proposals"
    )
    message: Mapped["Message"] = relationship("Message", back_populates="proposals")
    item_events: Mapped[list["ItemEvent"]] = relationship(
        "ItemEvent", back_populates="proposal"
    )

    def __repr__(self) -> str:
        return f"<Proposal(id={self.id}, status={self.status}, version={self.version})>"
