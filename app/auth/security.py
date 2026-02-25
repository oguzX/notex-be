"""Authentication security utilities."""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID

import jwt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.user import User
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session

logger = structlog.get_logger(__name__)

security = HTTPBearer(auto_error=False)


def hash_token(token: str) -> str:
    """Hash a token using SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: UUID) -> tuple[str, int]:
    """
    Create a JWT access token.
    
    Returns:
        Tuple of (token, expires_in_seconds)
    """
    settings = get_settings()
    expires_in = settings.ACCESS_TOKEN_TTL_SECONDS
    expire = datetime.utcnow() + timedelta(seconds=expires_in)
    
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    
    token = jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    
    return token, expires_in


def decode_access_token(token: str) -> UUID:
    """
    Decode and validate a JWT access token.
    
    Returns:
        User ID from token
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    settings = get_settings()
    
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return UUID(user_id_str)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> User:
    """
    Get the current authenticated user from request.
    
    Dependency that extracts and validates the access token,
    then loads the user from database.
    
    Raises:
        HTTPException: 401 if token missing, invalid, or user not found
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = decode_access_token(credentials.credentials)
    
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    return user
