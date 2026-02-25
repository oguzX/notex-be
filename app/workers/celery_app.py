"""Celery application configuration."""

import asyncio

from celery import Celery
from celery.signals import worker_init

from app.core.config import get_settings

settings = get_settings()

# Create Celery app
celery_app = Celery(
    "notex",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

# Configure Celery
celery_app.conf.update(
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)


@worker_init.connect
def init_worker(**kwargs):
    """Initialize database and event bus when worker starts."""
    from app.core.logging import configure_logging
    from app.db.session import init_db
    from app.events.bus import init_event_bus
    import structlog
    
    # Configure logging first
    configure_logging()
    logger = structlog.get_logger(__name__)
    
    # Create event loop for initialization
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Initialize database
        loop.run_until_complete(init_db())
        logger.info("celery_worker_db_initialized")
        
        # Initialize event bus
        loop.run_until_complete(init_event_bus())
        logger.info("celery_worker_event_bus_initialized")
    except Exception as e:
        logger.error("celery_worker_init_failed", error=str(e))
        raise


def get_celery_app() -> Celery:
    """Get Celery app instance."""
    return celery_app
