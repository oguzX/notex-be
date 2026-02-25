"""ID generation utilities."""

import secrets
import time
import uuid


def generate_id() -> uuid.UUID:
    """Generate a new UUID."""
    return uuid.uuid4()


def generate_id_str() -> str:
    """Generate a new UUID as string."""
    return str(uuid.uuid4())


def generate_refresh_token() -> str:
    """Generate a secure random refresh token."""
    return secrets.token_urlsafe(48)


def generate_clarification_id() -> str:
    """
    Generate a unique clarification ID with prefix.
    
    Format: clr_<timestamp_hex>_<random_hex>
    This ensures uniqueness and sortability.
    """
    timestamp_hex = hex(int(time.time() * 1000))[2:]
    random_hex = secrets.token_hex(8)
    return f"clr_{timestamp_hex}_{random_hex}"
