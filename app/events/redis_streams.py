"""Redis Streams implementation for persistent event storage."""

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.config import get_settings
from app.schemas.events import WsEvent

logger = structlog.get_logger(__name__)


class RedisStreams:
    """Redis Streams for persistent event storage."""

    def __init__(self):
        self.settings = get_settings()
        self.redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Initialize Redis connection."""
        self.redis = await aioredis.from_url(
            str(self.settings.REDIS_URL),
            decode_responses=True,
        )
        logger.info("redis_streams_connected")

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
        logger.info("redis_streams_closed")

    def _get_stream_key(self, conversation_id: str) -> str:
        """Get stream key for conversation."""
        return f"{self.settings.EVENTS_STREAM_PREFIX}{conversation_id}"

    async def append(self, event: WsEvent) -> str | None:
        """
        Append event to stream.
        
        Returns the stream message ID.
        """
        if not self.redis:
            logger.error("redis_not_connected")
            return None
        
        stream_key = self._get_stream_key(str(event.conversation_id))
        
        try:
            # Convert event to flat dict for Redis
            event_data = {
                "type": event.type.value,
                "conversation_id": str(event.conversation_id),
                "message_id": str(event.message_id) if event.message_id else "",
                "proposal_id": str(event.proposal_id) if event.proposal_id else "",
                "version": str(event.version) if event.version else "",
                "data": json.dumps(event.data) if event.data else "{}",
                "ts": event.ts.isoformat(),
            }
            
            message_id = await self.redis.xadd(
                stream_key,
                event_data,
                maxlen=self.settings.EVENTS_MAX_STREAM_LEN,
            )
            
            logger.debug(
                "event_appended_to_stream",
                stream_key=stream_key,
                message_id=message_id,
                event_type=event.type.value,
            )
            
            return message_id
            
        except Exception as e:
            logger.error("stream_append_error", error=str(e), stream_key=stream_key)
            return None

    async def read_events(
        self,
        conversation_id: str,
        start: str = "0",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """Read events from stream."""
        if not self.redis:
            return []
        
        stream_key = self._get_stream_key(conversation_id)
        
        try:
            events = await self.redis.xrange(stream_key, min=start, count=count)
            
            result = []
            for message_id, data in events:
                result.append({
                    "message_id": message_id,
                    **data,
                })
            
            return result
            
        except Exception as e:
            logger.error("stream_read_error", error=str(e), stream_key=stream_key)
            return []
