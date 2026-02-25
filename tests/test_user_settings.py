"""Tests for user settings: timezone, metas, and options."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.meta import Meta
from app.db.models.user import User
from app.db.models.user_options import UserOptions
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.user_settings_repo import UserSettingsRepository, _deep_merge
from app.schemas.user_settings_validators import validate_iana_timezone
from app.services.user_settings_service import UserSettingsService
from app.schemas.user_settings import UserUpdateRequest


# ---------------------------------------------------------------------------
# Timezone validation
# ---------------------------------------------------------------------------


class TestTimezoneValidation:
    """Test IANA timezone validation."""

    def test_valid_timezone_accepted(self):
        tz = validate_iana_timezone("Europe/Istanbul")
        assert tz == "Europe/Istanbul"

    def test_utc_accepted(self):
        tz = validate_iana_timezone("UTC")
        assert tz == "UTC"

    def test_america_new_york_accepted(self):
        tz = validate_iana_timezone("America/New_York")
        assert tz == "America/New_York"

    def test_invalid_timezone_rejected(self):
        with pytest.raises(ValueError, match="Invalid IANA timezone"):
            validate_iana_timezone("Invalid/Zone")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="Invalid IANA timezone"):
            validate_iana_timezone("")

    def test_numeric_offset_rejected(self):
        with pytest.raises(ValueError, match="Invalid IANA timezone"):
            validate_iana_timezone("+03:00")


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Test the deep-merge utility."""

    def test_simple_scalar_replacement(self):
        base = {"a": 1}
        patch = {"a": 2}
        assert _deep_merge(base, patch) == {"a": 2}

    def test_new_key_added(self):
        base = {"a": 1}
        patch = {"b": 2}
        assert _deep_merge(base, patch) == {"a": 1, "b": 2}

    def test_nested_dict_merge(self):
        base = {"ui": {"theme": "light", "font_size": 14}}
        patch = {"ui": {"theme": "dark"}}
        result = _deep_merge(base, patch)
        assert result == {"ui": {"theme": "dark", "font_size": 14}}

    def test_list_replaced_not_merged(self):
        base = {"tags": [1, 2, 3]}
        patch = {"tags": [4, 5]}
        assert _deep_merge(base, patch) == {"tags": [4, 5]}

    def test_deeply_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        patch = {"a": {"b": {"c": 99}}}
        assert _deep_merge(base, patch) == {"a": {"b": {"c": 99, "d": 2}}}

    def test_empty_base(self):
        assert _deep_merge({}, {"x": 1}) == {"x": 1}

    def test_empty_patch(self):
        assert _deep_merge({"x": 1}, {}) == {"x": 1}

    def test_original_not_mutated(self):
        base = {"a": 1}
        _deep_merge(base, {"a": 2})
        assert base == {"a": 1}


# ---------------------------------------------------------------------------
# Guest registration with timezone (API level)
# ---------------------------------------------------------------------------


class TestGuestRegistrationTimezone:
    """Test that POST /register/guest handles timezone."""

    @pytest.mark.asyncio
    async def test_register_guest_with_timezone(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Guest registration should persist timezone."""
        from uuid import uuid4

        client_uuid = uuid4()
        response = await client.post(
            "/register/guest",
            json={
                "client_uuid": str(client_uuid),
                "timezone": "Europe/Istanbul",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["timezone"] == "Europe/Istanbul"

        # Verify in DB
        repo = UserRepository(test_session)
        user = await repo.get_by_client_uuid(client_uuid)
        assert user is not None
        assert user.timezone == "Europe/Istanbul"

    @pytest.mark.asyncio
    async def test_register_guest_without_timezone(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Timezone should be null if not provided."""
        from uuid import uuid4

        client_uuid = uuid4()
        response = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid)},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["timezone"] is None

    @pytest.mark.asyncio
    async def test_register_guest_invalid_timezone(
        self, client: AsyncClient
    ):
        """Invalid timezone should be rejected with 422."""
        from uuid import uuid4

        response = await client.post(
            "/register/guest",
            json={
                "client_uuid": str(uuid4()),
                "timezone": "Not/A/Timezone",
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Repository-level tests
# ---------------------------------------------------------------------------


class TestUserSettingsRepository:
    """Repository-level tests for metas and options."""

    @pytest.mark.asyncio
    async def test_update_timezone(self, test_session: AsyncSession):
        user_repo = UserRepository(test_session)
        user = await user_repo.create_guest(
            __import__("uuid").uuid4(), timezone=None
        )
        await test_session.flush()

        settings_repo = UserSettingsRepository(test_session)
        updated = await settings_repo.update_timezone(user.id, "America/Chicago")
        assert updated.timezone == "America/Chicago"

    @pytest.mark.asyncio
    async def test_upsert_user_options_creates_row(self, test_session: AsyncSession):
        user_repo = UserRepository(test_session)
        user = await user_repo.create_guest(__import__("uuid").uuid4())
        await test_session.flush()

        settings_repo = UserSettingsRepository(test_session)
        opts = await settings_repo.upsert_user_options(
            user.id, {"notifications": {"push": True}}
        )
        assert opts.settings_json == {"notifications": {"push": True}}

    @pytest.mark.asyncio
    async def test_upsert_user_options_deep_merges(self, test_session: AsyncSession):
        user_repo = UserRepository(test_session)
        user = await user_repo.create_guest(__import__("uuid").uuid4())
        await test_session.flush()

        settings_repo = UserSettingsRepository(test_session)
        await settings_repo.upsert_user_options(
            user.id, {"notifications": {"push": True, "email": True}}
        )
        opts = await settings_repo.upsert_user_options(
            user.id, {"notifications": {"email": False}, "ui": {"theme": "dark"}}
        )
        assert opts.settings_json == {
            "notifications": {"push": True, "email": False},
            "ui": {"theme": "dark"},
        }

    @pytest.mark.asyncio
    async def test_attach_detach_metas(self, test_session: AsyncSession):
        """Attach and detach metas and verify idempotency."""
        user_repo = UserRepository(test_session)
        user = await user_repo.create_guest(__import__("uuid").uuid4())

        # Create meta rows
        meta1 = Meta(key="beta_user", name="Beta User", type="flag")
        meta2 = Meta(key="wants_push", name="Wants Push", type="flag")
        test_session.add_all([meta1, meta2])
        await test_session.flush()

        settings_repo = UserSettingsRepository(test_session)

        # Attach
        await settings_repo.attach_metas(user.id, [meta1.id, meta2.id])
        user_metas = await settings_repo.get_user_metas(user.id)
        assert len(user_metas) == 2

        # Idempotent attach (should not raise)
        await settings_repo.attach_metas(user.id, [meta1.id])
        user_metas = await settings_repo.get_user_metas(user.id)
        assert len(user_metas) == 2

        # Detach one
        await settings_repo.detach_metas(user.id, [meta1.id])
        user_metas = await settings_repo.get_user_metas(user.id)
        assert len(user_metas) == 1
        assert user_metas[0].meta.key == "wants_push"

        # Idempotent detach (already gone, should not raise)
        await settings_repo.detach_metas(user.id, [meta1.id])


# ---------------------------------------------------------------------------
# PATCH /user/update  (API level)
# ---------------------------------------------------------------------------


class TestUserUpdateEndpoint:
    """Integration tests for PATCH /user/update."""

    async def _register_guest(self, client: AsyncClient, timezone: str | None = None):
        """Helper to register a guest and return (user_id, access_token)."""
        from uuid import uuid4

        body: dict = {"client_uuid": str(uuid4())}
        if timezone:
            body["timezone"] = timezone
        resp = await client.post("/register/guest", json=body)
        assert resp.status_code == 201
        data = resp.json()
        return data["user_id"], data["access_token"]

    @pytest.mark.asyncio
    async def test_update_timezone(self, client: AsyncClient, test_session: AsyncSession):
        user_id, token = await self._register_guest(client)

        resp = await client.patch(
            "/v1/user/update",
            json={"timezone": "Asia/Tokyo"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["timezone"] == "Asia/Tokyo"

    @pytest.mark.asyncio
    async def test_update_invalid_timezone_422(self, client: AsyncClient):
        _, token = await self._register_guest(client)

        resp = await client.patch(
            "/v1/user/update",
            json={"timezone": "Fake/Zone"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_options_creates_row(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user_id, token = await self._register_guest(client)

        resp = await client.patch(
            "/v1/user/update",
            json={"options": {"ui": {"theme": "dark"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["options"]["ui"]["theme"] == "dark"

    @pytest.mark.asyncio
    async def test_update_options_deep_merge(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        user_id, token = await self._register_guest(client)
        headers = {"Authorization": f"Bearer {token}"}

        # First patch
        await client.patch(
            "/v1/user/update",
            json={"options": {"notifications": {"push": True, "email": True}}},
            headers=headers,
        )

        # Second patch – should merge
        resp = await client.patch(
            "/v1/user/update",
            json={"options": {"notifications": {"email": False}, "ui": {"theme": "dark"}}},
            headers=headers,
        )
        assert resp.status_code == 200
        opts = resp.json()["options"]
        assert opts["notifications"]["push"] is True
        assert opts["notifications"]["email"] is False
        assert opts["ui"]["theme"] == "dark"

    @pytest.mark.asyncio
    async def test_attach_unknown_meta_404(self, client: AsyncClient):
        _, token = await self._register_guest(client)

        resp = await client.patch(
            "/v1/user/update",
            json={"metas": {"attach": ["nonexistent_key"]}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_attach_and_detach_metas(
        self, client: AsyncClient, test_session: AsyncSession
    ):
        """Full lifecycle: create metas in DB, attach, verify, detach."""
        _, token = await self._register_guest(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Seed metas
        meta1 = Meta(key="beta_user", name="Beta User", type="flag")
        meta2 = Meta(key="early_access", name="Early Access", type="flag")
        test_session.add_all([meta1, meta2])
        await test_session.commit()

        # Attach both
        resp = await client.patch(
            "/v1/user/update",
            json={"metas": {"attach": ["beta_user", "early_access"]}},
            headers=headers,
        )
        assert resp.status_code == 200
        meta_keys = {m["key"] for m in resp.json()["metas"]}
        assert meta_keys == {"beta_user", "early_access"}

        # Detach one
        resp = await client.patch(
            "/v1/user/update",
            json={"metas": {"detach": ["beta_user"]}},
            headers=headers,
        )
        assert resp.status_code == 200
        meta_keys = {m["key"] for m in resp.json()["metas"]}
        assert meta_keys == {"early_access"}

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, client: AsyncClient):
        resp = await client.patch(
            "/v1/user/update",
            json={"timezone": "UTC"},
        )
        assert resp.status_code == 401
