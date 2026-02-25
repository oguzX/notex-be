"""Meta catalog model."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user_meta import UserMeta


class Meta(Base):
    """Meta definition that can be attached to users.

    Represents a flag, tag, or feature marker.  Each meta has a unique
    ``key`` used for API lookups and a human-readable ``name``.
    """

    __tablename__ = "metas"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="flag")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    user_metas: Mapped[list["UserMeta"]] = relationship(
        "UserMeta", back_populates="meta", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Meta(id={self.id}, key={self.key})>"
