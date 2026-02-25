"""Repository for user settings: metas, options, timezone."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.meta import Meta
from app.db.models.user import User
from app.db.models.user_meta import UserMeta
from app.db.models.user_options import UserOptions


class UserSettingsRepository:
    """Repository for user-settings related DB operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Timezone
    # ------------------------------------------------------------------

    async def update_timezone(self, user_id: UUID, timezone: str) -> User:
        """Set the timezone on the users row.  Returns the updated user."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one()
        user.timezone = timezone
        await self.session.flush()
        return user

    # ------------------------------------------------------------------
    # Metas
    # ------------------------------------------------------------------

    async def get_meta_by_key(self, key: str) -> Meta | None:
        result = await self.session.execute(
            select(Meta).where(Meta.key == key)
        )
        return result.scalar_one_or_none()

    async def get_metas_by_keys(self, keys: list[str]) -> list[Meta]:
        if not keys:
            return []
        result = await self.session.execute(
            select(Meta).where(Meta.key.in_(keys))
        )
        return list(result.scalars().all())

    async def attach_metas(self, user_id: UUID, meta_ids: list[UUID]) -> None:
        """Attach metas to user.  Idempotent – ignores duplicates."""
        if not meta_ids:
            return
        stmt = pg_insert(UserMeta).values(
            [{"user_id": user_id, "meta_id": mid} for mid in meta_ids]
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["user_id", "meta_id"]
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def detach_metas(self, user_id: UUID, meta_ids: list[UUID]) -> None:
        """Detach metas from user.  Idempotent – ignores missing."""
        if not meta_ids:
            return
        await self.session.execute(
            delete(UserMeta).where(
                UserMeta.user_id == user_id,
                UserMeta.meta_id.in_(meta_ids),
            )
        )
        await self.session.flush()

    async def get_user_metas(self, user_id: UUID) -> list[UserMeta]:
        """Return all UserMeta rows for a user, with the Meta eagerly loaded."""
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(UserMeta)
            .options(selectinload(UserMeta.meta))
            .where(UserMeta.user_id == user_id)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    async def get_user_options(self, user_id: UUID) -> UserOptions | None:
        result = await self.session.execute(
            select(UserOptions).where(UserOptions.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert_user_options(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> UserOptions:
        """Create or deep-merge into user_options.settings_json."""
        opts = await self.get_user_options(user_id)
        if opts is None:
            opts = UserOptions(user_id=user_id, settings_json={})
            self.session.add(opts)
            await self.session.flush()

        merged = _deep_merge(opts.settings_json or {}, patch)
        opts.settings_json = merged
        await self.session.flush()
        return opts


# ---------------------------------------------------------------------------
# Deep-merge helper
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *patch* into *base*.

    Rules:
    - dicts merge recursively
    - lists are replaced wholesale
    - scalars are replaced
    """
    result = dict(base)
    for key, value in patch.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
