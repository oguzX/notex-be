"""HTTP/SSE Bridge for FastMCP server.

This module provides a Streamable HTTP interface to the existing FastMCP server,
allowing OpenAI's Responses API to connect and discover tools dynamically.

Implements the MCP Streamable HTTP transport protocol as defined in:
https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.mcp_server.server import mcp

logger = structlog.get_logger(__name__)

# MCP Protocol Version (from spec)
MCP_PROTOCOL_VERSION = "2025-03-26"

app = FastAPI(
    title="Notex MCP Bridge",
    description="Streamable HTTP bridge for FastMCP tools (MCP Protocol 2025-03-26)",
    version="1.0.0",
)


async def _handle_mcp_request(request_data: dict[str, Any]) -> dict[str, Any] | None:
    """Handle MCP protocol requests and route to FastMCP tools.
    
    Args:
        request_data: MCP request payload
        
    Returns:
        MCP response payload, or None for notifications
    """
    # Validate JSON-RPC 2.0 structure
    if "jsonrpc" not in request_data or request_data["jsonrpc"] != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": request_data.get("id"),
            "error": {
                "code": -32600,
                "message": "Invalid Request: missing or invalid jsonrpc field",
            },
        }
    
    method = request_data.get("method")
    params = request_data.get("params", {})
    request_id = request_data.get("id")
    
    # Check if this is a notification (no id field)
    is_notification = "id" not in request_data
    
    if not method:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32600,
                "message": "Invalid Request: missing method field",
            },
        }
    
    logger.info("mcp_request", method=method, request_id=request_id, is_notification=is_notification, params=params)
    
    try:
        if method == "tools/list":
            # List all registered tools
            tools_list = []
            mcp_tools_dict = await mcp.get_tools()
            
            for tool_name, tool in mcp_tools_dict.items():
                # FastMCP FunctionTool has input_schema attribute
                input_schema = {
                    "type": "object",
                    "properties": {},
                }
                
                # Try to get schema from tool.parameters (FastMCP 2.x)
                if hasattr(tool, 'parameters') and tool.parameters:
                    input_schema = tool.parameters
                
                schema = {
                    "name": tool.name,
                    "description": tool.description or f"Execute {tool.name}",
                    "inputSchema": input_schema,
                }
                tools_list.append(schema)
            
            result = {"tools": tools_list}
            logger.info("mcp_tools_listed", tool_count=len(tools_list), tools=[t["name"] for t in tools_list])
            
        elif method == "tools/call":
            # Execute a tool
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            
            if not tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "Missing required parameter: name",
                    },
                }
            
            # Get all tools and check if tool exists
            mcp_tools_dict = await mcp.get_tools()
            tool = mcp_tools_dict.get(tool_name)
            
            if not tool:
                available_tools = list(mcp_tools_dict.keys())
                logger.warning("mcp_tool_not_found", tool=tool_name, available_tools=available_tools)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}",
                        "data": {"available_tools": available_tools},
                    },
                }
            
            logger.info("mcp_tool_call_start", tool=tool_name, args=tool_args)
            start_time = asyncio.get_event_loop().time()
            
            # Execute the tool using FastMCP's tool.run() method
            try:
                tool_result_obj = await tool.run(arguments=tool_args)
                
                execution_time = asyncio.get_event_loop().time() - start_time
                logger.info("mcp_tool_call_complete", tool=tool_name, execution_time_ms=int(execution_time * 1000))
                
                # Extract content from ToolResult object
                content = []
                for item in tool_result_obj.content:
                    if hasattr(item, 'text'):
                        content.append({"type": "text", "text": item.text})
                    else:
                        content.append({"type": "text", "text": str(item)})
                
                result = {"content": content}
                
            except TypeError as e:
                logger.error("mcp_tool_args_error", tool=tool_name, error=str(e))
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": f"Invalid arguments for tool {tool_name}: {str(e)}",
                    },
                }
            except Exception as e:
                execution_time = asyncio.get_event_loop().time() - start_time
                logger.error("mcp_tool_execution_error", tool=tool_name, error=str(e), execution_time_ms=int(execution_time * 1000))
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": f"Tool execution failed: {str(e)}",
                    },
                }
            
        elif method == "initialize":
            # MCP initialization handshake
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "notex-mcp",
                    "version": "1.0.0",
                },
            }
            logger.info("mcp_initialized", protocol_version=MCP_PROTOCOL_VERSION)
            
        elif method.startswith("notifications/"):
            # All notifications - return None to indicate 202 Accepted
            logger.info("mcp_notification_received", method=method)
            return None
            
        else:
            logger.warning("mcp_unknown_method", method=method)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown method: {method}",
                },
            }
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        
    except Exception as e:
        logger.error("mcp_request_error", method=method, error=str(e), error_type=type(e).__name__)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}",
            },
        }


@app.api_route("/mcp", methods=["GET", "POST"])
async def mcp_endpoint(request: Request) -> Response:
    """Streamable HTTP endpoint for MCP requests.
    
    Implements MCP Streamable HTTP transport protocol.
    Supports both GET (for SSE stream) and POST (for JSON-RPC messages).
    
    Per the MCP spec:
    - POST with requests: Return JSON or SSE stream
    - POST with notifications only: Return 202 Accepted with no body
    - GET: Return SSE stream or 405 Method Not Allowed
    """
    try:
        if request.method == "GET":
            # GET request - return SSE stream with server capabilities
            logger.info("mcp_get_request_sse")
            
            # According to MCP spec, GET can be used to open SSE stream
            # for server-to-client communication
            async def event_generator() -> AsyncIterator[dict]:
                # Send initial capabilities
                tools_list = await _get_tools_list()
                init_data = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {
                            "tools": {"listChanged": False},
                        },
                        "serverInfo": {
                            "name": "notex-mcp",
                            "version": "1.0.0",
                        },
                    },
                }
                yield {"data": json.dumps(init_data)}
            
            return EventSourceResponse(event_generator())
        else:
            # POST request - handle JSON-RPC
            request_data = await request.json()
            
            # Log the raw request for debugging
            logger.debug("mcp_raw_request", data=request_data)
            
            response = await _handle_mcp_request(request_data)
            
            # For notifications (None response), return 202 Accepted per MCP spec
            if response is None:
                logger.info("mcp_notification_accepted")
                return Response(status_code=202)
            
            # Return JSON response with proper content type
            return JSONResponse(
                content=response,
                media_type="application/json",
            )
            
    except json.JSONDecodeError as e:
        logger.error("mcp_json_decode_error", error=str(e))
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {str(e)}",
                },
            },
        )


async def _get_tools_list() -> list[dict[str, Any]]:
    """Get list of available tools from FastMCP.
    
    Returns:
        List of tool schemas
    """
    tools_list = []
    mcp_tools_dict = await mcp.get_tools()
    
    for tool_name, tool in mcp_tools_dict.items():
        input_schema = {
            "type": "object",
            "properties": {},
        }
        
        # Try to get schema from tool.parameters (FastMCP 2.x)
        if hasattr(tool, 'parameters') and tool.parameters:
            input_schema = tool.parameters
        
        schema = {
            "name": tool.name,
            "description": tool.description or f"Execute {tool.name}",
            "inputSchema": input_schema,
        }
        tools_list.append(schema)
    
    return tools_list


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "mcp-bridge"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(app, host="0.0.0.0", port=8001)
