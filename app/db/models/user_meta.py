"""UserMeta association model (users <-> metas)."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.meta import Meta
    from app.db.models.user import User


class UserMeta(Base):
    """Association between a user and a meta definition.

    Composite primary key on ``(user_id, meta_id)`` guarantees uniqueness.
    """

    __tablename__ = "user_metas"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    meta_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("metas.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="user_metas")
    meta: Mapped["Meta"] = relationship("Meta", back_populates="user_metas")

    def __repr__(self) -> str:
        return f"<UserMeta(user_id={self.user_id}, meta_id={self.meta_id})>"
