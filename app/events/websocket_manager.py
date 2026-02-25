"""WebSocket connection manager for realtime events."""

import asyncio
from typing import Any
from uuid import UUID

import structlog
from fastapi import WebSocket

from app.events.bus import get_event_bus

logger = structlog.get_logger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per conversation."""

    def __init__(self):
        # conversation_id -> list of WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}
        # conversation_id -> subscription task
        self.subscription_tasks: dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, conversation_id: UUID) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        
        conv_id_str = str(conversation_id)
        
        if conv_id_str not in self.active_connections:
            self.active_connections[conv_id_str] = []
        
        self.active_connections[conv_id_str].append(websocket)
        
        # Start subscription task if not already running
        if conv_id_str not in self.subscription_tasks:
            task = asyncio.create_task(
                self._subscribe_and_broadcast(conv_id_str)
            )
            self.subscription_tasks[conv_id_str] = task
        
        logger.info(
            "websocket_connected",
            conversation_id=conv_id_str,
            connections=len(self.active_connections[conv_id_str]),
        )

    def disconnect(self, websocket: WebSocket, conversation_id: UUID) -> None:
        """Unregister a WebSocket connection."""
        conv_id_str = str(conversation_id)
        
        if conv_id_str in self.active_connections:
            if websocket in self.active_connections[conv_id_str]:
                self.active_connections[conv_id_str].remove(websocket)
            
            # If no more connections, cancel subscription task
            if not self.active_connections[conv_id_str]:
                del self.active_connections[conv_id_str]
                
                if conv_id_str in self.subscription_tasks:
                    self.subscription_tasks[conv_id_str].cancel()
                    del self.subscription_tasks[conv_id_str]
        
        logger.info(
            "websocket_disconnected",
            conversation_id=conv_id_str,
            connections=len(self.active_connections.get(conv_id_str, [])),
        )

    async def broadcast_to_conversation(
        self,
        conversation_id: str,
        message: str,
    ) -> None:
        """Broadcast message to all connections for a conversation."""
        if conversation_id not in self.active_connections:
            return
        
        disconnected = []
        
        for connection in self.active_connections[conversation_id]:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(
                    "websocket_send_error",
                    error=str(e),
                    conversation_id=conversation_id,
                )
                disconnected.append(connection)
        
        # Clean up disconnected sockets
        for conn in disconnected:
            if conn in self.active_connections[conversation_id]:
                self.active_connections[conversation_id].remove(conn)

    async def _subscribe_and_broadcast(self, conversation_id: str) -> None:
        """
        Subscribe to Redis PubSub and broadcast to WebSocket connections.
        
        This runs as a background task per conversation.
        """
        try:
            event_bus = get_event_bus()
            pubsub = await event_bus.subscribe(conversation_id)
            
            logger.info("subscription_task_started", conversation_id=conversation_id)
            
            while conversation_id in self.active_connections:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    
                    if message and message["type"] == "message":
                        data = message["data"]
                        await self.broadcast_to_conversation(conversation_id, data)
                    
                    await asyncio.sleep(0.01)  # Small delay to prevent busy loop
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(
                        "subscription_error",
                        error=str(e),
                        conversation_id=conversation_id,
                    )
                    await asyncio.sleep(1)  # Back off on error
            
            # Clean up
            await event_bus.unsubscribe(pubsub, conversation_id)
            logger.info("subscription_task_stopped", conversation_id=conversation_id)
            
        except asyncio.CancelledError:
            logger.info("subscription_task_cancelled", conversation_id=conversation_id)
        except Exception as e:
            logger.error(
                "subscription_task_error",
                error=str(e),
                conversation_id=conversation_id,
            )


# Global connection manager instance
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Get or create global connection manager."""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
