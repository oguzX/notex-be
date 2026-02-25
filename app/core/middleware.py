"""FastAPI middleware components."""

import time
import uuid
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add X-Request-ID header and bind to logging context."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with request ID."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        
        # Bind request ID to logging context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )
        
        # Store in request state for access in route handlers
        request.state.request_id = request_id
        
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        # Log request completion
        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        
        return response
