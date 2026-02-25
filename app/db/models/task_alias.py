"""Task alias model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TaskAlias(Base):
    """Task alias model for natural language references."""

    __tablename__ = "task_aliases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # llm_generated, user_created, system_inferred
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="aliases")

    def __repr__(self) -> str:
        return f"<TaskAlias(id={self.id}, alias={self.alias[:30]})>"
