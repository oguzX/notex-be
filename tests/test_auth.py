"""Test authentication functionality."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, decode_access_token, hash_token
from app.db.models.user import User
from app.db.repositories.refresh_token_repo import RefreshTokenRepository
from app.db.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService


class TestGuestRegistration:
    """Test guest user registration."""

    @pytest.mark.asyncio
    async def test_register_guest_returns_tokens(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that guest registration returns valid tokens."""
        from uuid import uuid4

        client_uuid = uuid4()
        response = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid)},
        )

        assert response.status_code == 201
        data = response.json()

        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 900  # Default 15 minutes
        assert "user_id" in data

        # Verify user was created
        user_repo = UserRepository(test_db_session)
        user = await user_repo.get_by_client_uuid(client_uuid)
        assert user is not None
        assert user.kind == "GUEST"
        assert user.client_uuid == client_uuid

    @pytest.mark.asyncio
    async def test_register_guest_idempotent(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that registering same client_uuid returns tokens for existing user."""
        from uuid import uuid4

        client_uuid = uuid4()

        # Register first time
        response1 = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid)},
        )
        assert response1.status_code == 201
        user_id1 = response1.json()["user_id"]

        # Register second time with same client_uuid
        response2 = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid)},
        )
        assert response2.status_code == 201
        user_id2 = response2.json()["user_id"]

        # Same user
        assert user_id1 == user_id2


class TestTokenRefresh:
    """Test token refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_rotates_tokens(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that refreshing tokens rotates the refresh token."""
        from uuid import uuid4

        # Register guest
        client_uuid = uuid4()
        register_response = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid)},
        )
        old_refresh_token = register_response.json()["refresh_token"]

        # Refresh tokens
        refresh_response = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )
        assert refresh_response.status_code == 200
        new_refresh_token = refresh_response.json()["refresh_token"]

        # Old and new refresh tokens should be different
        assert old_refresh_token != new_refresh_token

        # Old refresh token should no longer work
        invalid_refresh_response = await client.post(
            "/auth/refresh",
            json={"refresh_token": old_refresh_token},
        )
        assert invalid_refresh_response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Test that invalid refresh token returns 401."""
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )
        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]


class TestProtectedEndpoints:
    """Test authentication on protected endpoints."""

    @pytest.mark.asyncio
    async def test_protected_route_requires_auth(self, client: AsyncClient):
        """Test that /v1 endpoints require authentication."""
        response = await client.post("/v1/conversations")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_with_valid_token(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that valid token allows access to protected endpoints."""
        from uuid import uuid4

        # Register and get token
        client_uuid = uuid4()
        register_response = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid)},
        )
        access_token = register_response.json()["access_token"]

        # Access protected endpoint
        response = await client.post(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_protected_route_with_expired_token(self, client: AsyncClient):
        """Test that expired token returns 401."""
        from datetime import datetime, timedelta
        from uuid import uuid4

        import jwt

        from app.core.config import get_settings

        settings = get_settings()

        # Create expired token
        user_id = uuid4()
        expire = datetime.utcnow() - timedelta(hours=1)
        payload = {
            "sub": str(user_id),
            "exp": expire,
            "iat": datetime.utcnow() - timedelta(hours=2),
        }
        expired_token = jwt.encode(
            payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        # Try to access protected endpoint
        response = await client.post(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401


class TestConversationOwnership:
    """Test conversation ownership enforcement."""

    @pytest.mark.asyncio
    async def test_conversation_ownership_enforced(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """Test that users can only access their own conversations."""
        from uuid import uuid4

        # Create two users
        client_uuid1 = uuid4()
        client_uuid2 = uuid4()

        response1 = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid1)},
        )
        token1 = response1.json()["access_token"]

        response2 = await client.post(
            "/register/guest",
            json={"client_uuid": str(client_uuid2)},
        )
        token2 = response2.json()["access_token"]

        # User 1 creates a conversation
        conv_response = await client.post(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert conv_response.status_code == 201
        conversation_id = conv_response.json()["id"]

        # User 2 tries to access user 1's conversation
        get_response = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert get_response.status_code == 404  # Not found (not 403, to avoid info leak)

        # User 1 can access their own conversation
        get_response = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert get_response.status_code == 200


class TestSecurityUtilities:
    """Test security utility functions."""

    def test_hash_token_is_deterministic(self):
        """Test that hashing same token produces same hash."""
        token = "test-token-12345"
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        assert hash1 == hash2

    def test_hash_token_different_for_different_tokens(self):
        """Test that different tokens produce different hashes."""
        hash1 = hash_token("token1")
        hash2 = hash_token("token2")
        assert hash1 != hash2

    def test_create_and_decode_access_token(self):
        """Test creating and decoding access token."""
        from uuid import uuid4

        user_id = uuid4()
        token, expires_in = create_access_token(user_id)

        assert isinstance(token, str)
        assert expires_in == 900  # Default

        decoded_user_id = decode_access_token(token)
        assert decoded_user_id == user_id

    def test_decode_invalid_token_raises(self):
        """Test that decoding invalid token raises HTTPException."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("invalid-token")

        assert exc_info.value.status_code == 401
