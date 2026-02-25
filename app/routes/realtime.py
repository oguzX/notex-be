"""Realtime endpoints (WebSocket and SSE)."""

import asyncio
from uuid import UUID

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from app.events.bus import get_event_bus
from app.events.websocket_manager import get_connection_manager

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.websocket("/ws/conversations/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: UUID):
    """
    WebSocket endpoint for realtime events.
    
    Clients connect here to receive events for a specific conversation.
    """
    manager = get_connection_manager()
    
    await manager.connect(websocket, conversation_id)
    
    try:
        # Keep connection alive and handle client messages if needed
        while True:
            try:
                # Receive message (for keepalive or commands)
                data = await websocket.receive_text()
                logger.debug("websocket_message_received", data=data)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error("websocket_error", error=str(e))
                break
            
            await asyncio.sleep(0.1)
            
    finally:
        manager.disconnect(websocket, conversation_id)


@router.get("/conversations/{conversation_id}/events")
async def sse_endpoint(conversation_id: UUID):
    """
    SSE endpoint for realtime events (alternative to WebSocket).
    
    Streams events as Server-Sent Events.
    """
    async def event_generator():
        """Generate SSE events."""
        try:
            event_bus = get_event_bus()
            pubsub = await event_bus.subscribe(str(conversation_id))
            
            logger.info("sse_client_connected", conversation_id=str(conversation_id))
            
            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    
                    if message and message["type"] == "message":
                        data = message["data"]
                        yield {
                            "event": "message",
                            "data": data,
                        }
                    
                    await asyncio.sleep(0.01)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("sse_error", error=str(e))
                    await asyncio.sleep(1)
            
            await event_bus.unsubscribe(pubsub, str(conversation_id))
            logger.info("sse_client_disconnected", conversation_id=str(conversation_id))
            
        except Exception as e:
            logger.error("sse_generator_error", error=str(e))
    
    return EventSourceResponse(event_generator())
