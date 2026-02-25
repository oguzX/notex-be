"""SQLAlchemy declarative base and common columns."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Naming convention for constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = metadata

    # Type annotation for type checkers
    __tablename__: str


def utcnow() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)
