"""Event bus implementation combining PubSub and Streams."""

import structlog

from app.events.redis_pubsub import RedisPubSub
from app.events.redis_streams import RedisStreams
from app.schemas.events import WsEvent

logger = structlog.get_logger(__name__)

# Global instances
_pubsub: RedisPubSub | None = None
_streams: RedisStreams | None = None


async def init_event_bus() -> None:
    """Initialize event bus components."""
    global _pubsub, _streams
    
    _pubsub = RedisPubSub()
    await _pubsub.connect()
    
    _streams = RedisStreams()
    await _streams.connect()
    
    logger.info("event_bus_initialized")


async def close_event_bus() -> None:
    """Close event bus connections."""
    global _pubsub, _streams
    
    if _pubsub:
        await _pubsub.close()
        _pubsub = None
    
    if _streams:
        await _streams.close()
        _streams = None
    
    logger.info("event_bus_closed")


def get_event_bus() -> "EventBus":
    """Get event bus instance."""
    if not _pubsub or not _streams:
        raise RuntimeError("Event bus not initialized. Call init_event_bus() first.")
    return EventBus(_pubsub, _streams)


class EventBus:
    """Unified event bus for publishing and subscribing to events."""

    def __init__(self, pubsub: RedisPubSub, streams: RedisStreams):
        self.pubsub = pubsub
        self.streams = streams

    async def publish(self, event: WsEvent) -> None:
        """
        Publish event to both PubSub (realtime) and Streams (persistent).
        """
        # Persist to stream
        await self.streams.append(event)
        
        # Broadcast via PubSub for realtime delivery
        await self.pubsub.publish(event)
        
        logger.debug(
            "event_published",
            conversation_id=str(event.conversation_id),
            event_type=event.type.value,
        )

    async def subscribe(self, conversation_id: str):
        """Subscribe to realtime events for a conversation."""
        return await self.pubsub.subscribe(conversation_id)

    async def unsubscribe(self, pubsub, conversation_id: str):
        """Unsubscribe from conversation events."""
        await self.pubsub.unsubscribe(pubsub, conversation_id)

    async def get_history(
        self,
        conversation_id: str,
        start: str = "0",
        count: int = 100,
    ) -> list[dict]:
        """Get event history from streams."""
        return await self.streams.read_events(conversation_id, start, count)
