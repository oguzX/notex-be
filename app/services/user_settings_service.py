"""Service layer for user settings (timezone, metas, options)."""

from typing import Any
from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.user_repo import UserRepository
from app.db.repositories.user_settings_repo import UserSettingsRepository
from app.schemas.user_settings import (
    MetasUpdatePayload,
    UserMetaItem,
    UserUpdateRequest,
    UserUpdateResponse,
)

logger = structlog.get_logger(__name__)


class UserSettingsService:
    """Orchestrates user-settings mutations inside a single transaction."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.settings_repo = UserSettingsRepository(session)

    async def update_user(
        self, user_id: UUID, payload: UserUpdateRequest
    ) -> UserUpdateResponse:
        """Apply all requested updates atomically and return the new state."""

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # 1. Timezone ---------------------------------------------------------
        if payload.timezone is not None:
            user = await self.settings_repo.update_timezone(user_id, payload.timezone)
            logger.info("user_timezone_updated", user_id=str(user_id), timezone=payload.timezone)

        # 2. Metas  -----------------------------------------------------------
        if payload.metas is not None:
            await self._process_metas(user_id, payload.metas)

        # 3. Options  ---------------------------------------------------------
        if payload.options is not None:
            await self.settings_repo.upsert_user_options(user_id, payload.options)
            logger.info("user_options_updated", user_id=str(user_id))

        await self.session.commit()

        # Build response  -----------------------------------------------------
        return await self._build_response(user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _process_metas(
        self, user_id: UUID, metas_payload: MetasUpdatePayload
    ) -> None:
        """Attach / detach metas.  Rejects unknown keys with 404."""

        if metas_payload.attach:
            found = await self.settings_repo.get_metas_by_keys(metas_payload.attach)
            found_keys = {m.key for m in found}
            missing = set(metas_payload.attach) - found_keys
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Unknown meta keys: {sorted(missing)}",
                )
            await self.settings_repo.attach_metas(
                user_id, [m.id for m in found]
            )
            logger.info(
                "user_metas_attached",
                user_id=str(user_id),
                keys=metas_payload.attach,
            )

        if metas_payload.detach:
            found = await self.settings_repo.get_metas_by_keys(metas_payload.detach)
            found_keys = {m.key for m in found}
            missing = set(metas_payload.detach) - found_keys
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Unknown meta keys: {sorted(missing)}",
                )
            await self.settings_repo.detach_metas(
                user_id, [m.id for m in found]
            )
            logger.info(
                "user_metas_detached",
                user_id=str(user_id),
                keys=metas_payload.detach,
            )

    async def _build_response(self, user_id: UUID) -> UserUpdateResponse:
        """Build the full UserUpdateResponse from current DB state."""
        user = await self.user_repo.get_by_id(user_id)
        assert user is not None

        # Metas
        user_metas = await self.settings_repo.get_user_metas(user_id)
        meta_items = [
            UserMetaItem(
                key=um.meta.key,
                name=um.meta.name,
                type=um.meta.type,
                attached_at=um.created_at,
            )
            for um in user_metas
        ]

        # Options
        opts = await self.settings_repo.get_user_options(user_id)
        options_dict: dict[str, Any] = opts.settings_json if opts else {}

        return UserUpdateResponse(
            user_id=str(user_id),
            timezone=user.timezone,
            metas=meta_items,
            options=options_dict,
        )
