"""Redis PubSub implementation for realtime events."""

import asyncio
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.config import get_settings
from app.schemas.events import WsEvent

logger = structlog.get_logger(__name__)


class RedisPubSub:
    """Redis PubSub for realtime event broadcasting."""

    def __init__(self):
        self.settings = get_settings()
        self.redis: aioredis.Redis | None = None
        self.pubsub: aioredis.client.PubSub | None = None

    async def connect(self) -> None:
        """Initialize Redis connection."""
        self.redis = await aioredis.from_url(
            str(self.settings.REDIS_URL),
            decode_responses=True,
        )
        logger.info("redis_pubsub_connected")

    async def close(self) -> None:
        """Close Redis connection."""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis:
            await self.redis.close()
        logger.info("redis_pubsub_closed")

    def _get_channel(self, conversation_id: str) -> str:
        """Get PubSub channel name for conversation."""
        return f"{self.settings.EVENTS_PUBSUB_PREFIX}{conversation_id}"

    async def publish(self, event: WsEvent) -> None:
        """Publish event to conversation channel."""
        if not self.redis:
            logger.error("redis_not_connected")
            return
        
        channel = self._get_channel(str(event.conversation_id))
        message = event.model_dump_json()
        
        try:
            await self.redis.publish(channel, message)
            logger.debug(
                "event_published",
                channel=channel,
                event_type=event.type.value,
            )
        except Exception as e:
            logger.error("publish_error", error=str(e), channel=channel)

    async def subscribe(self, conversation_id: str) -> aioredis.client.PubSub:
        """Subscribe to conversation channel."""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        channel = self._get_channel(conversation_id)
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        
        logger.info("subscribed_to_channel", channel=channel)
        return pubsub

    async def unsubscribe(self, pubsub: aioredis.client.PubSub, conversation_id: str) -> None:
        """Unsubscribe from conversation channel."""
        channel = self._get_channel(conversation_id)
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        logger.info("unsubscribed_from_channel", channel=channel)
