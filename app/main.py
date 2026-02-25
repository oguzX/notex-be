"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import (
    NotexException,
    general_exception_handler,
    http_exception_handler,
    notex_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.db.session import close_db, init_db
from app.events.bus import close_event_bus, init_event_bus
from app.routes import auth, conversations, devices, health, items, messages, notes, proposals, realtime, tasks, user_settings

# Configure logging first
configure_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Handle application startup and shutdown."""
    settings = get_settings()
    logger.info("starting_application", env=settings.ENV)
    
    # Initialize database
    await init_db()
    logger.info("database_initialized")
    
    # Initialize event bus
    await init_event_bus()
    logger.info("event_bus_initialized")
    
    yield
    
    # Cleanup
    logger.info("shutting_down_application")
    await close_event_bus()
    await close_db()
    logger.info("application_shutdown_complete")


# Create FastAPI application
settings = get_settings()
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
)

# Add middleware
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)

# Register exception handlers
app.add_exception_handler(NotexException, notex_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Register routes
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, tags=["auth"])
app.include_router(
    conversations.router,
    prefix=f"{settings.API_V1_PREFIX}/conversations",
    tags=["conversations"],
)
app.include_router(
    messages.router,
    prefix=f"{settings.API_V1_PREFIX}/conversations",
    tags=["messages"],
)
app.include_router(
    tasks.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["tasks"],
)
app.include_router(
    items.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["items"],
)
app.include_router(
    notes.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["notes"],
)
app.include_router(
    proposals.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["proposals"],
)
app.include_router(
    realtime.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["realtime"],
)
app.include_router(
    devices.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["devices"],
)
app.include_router(
    user_settings.router,
    prefix=f"{settings.API_V1_PREFIX}",
    tags=["user-settings"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Notex API",
        "docs": f"{settings.API_V1_PREFIX}/docs",
    }
