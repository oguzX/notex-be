# MCP Integration - OpenAI Responses API

This document describes the Model Context Protocol (MCP) integration for the Notex application, following OpenAI's "Tools, Connectors, and MCP" documentation.

## Overview

The system now supports **two execution modes**:

1. **Ops Mode** - Traditional task/note management via JSON operations (existing behavior)
2. **Tool Mode** - External tools (weather, FX) via MCP and OpenAI Responses API (new)

The LLM automatically routes requests between modes based on intent classification.

## Architecture

```
┌─────────────────┐
│  User Message   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Intent Classify │ ──► weather/FX keywords? → Tool Mode
└────────┬────────┘                            
         │                                      
         ▼                                      
    Ops Mode ──► generate_proposal() ──► JSON operations
```

### Tool Mode Flow

```
┌──────────────┐         ┌─────────────────┐         ┌─────────────┐
│ OpenAI       │         │ MCP HTTP Bridge │         │ FastMCP     │
│ Provider     │ ◄─────► │ (Port 8001)     │ ◄─────► │ Tools       │
└──────────────┘         └─────────────────┘         └─────────────┘
       │                                                      │
       │                                                      │
       ▼                                                      ▼
Responses API                                          weather_get
   + MCP tool config                                   fx_convert
   
Steps:
1. OpenAI calls MCP server via HTTP/SSE
2. MCP server lists available tools
3. Model decides which tool to call
4. MCP server executes tool
5. Result returned to OpenAI
6. Final response generated
```

## Components

### 1. MCP HTTP Bridge (`app/mcp_server/http_bridge.py`)

FastAPI server that exposes FastMCP tools via HTTP/SSE:

- **Endpoints:**
  - `GET /sse` - Server-Sent Events endpoint for OpenAI
  - `POST /mcp` - Direct HTTP endpoint for MCP requests
  - `GET /health` - Health check

- **Supported MCP Methods:**
  - `initialize` - Handshake
  - `tools/list` - List available tools
  - `tools/call` - Execute a tool

### 2. OpenAI Provider (`app/llm/openai_provider.py`)

Enhanced with two methods:

- `generate_proposal()` - Ops Mode (existing)
- `generate_tool_response()` - Tool Mode (new)

**Tool Mode Features:**
- Uses OpenAI Responses API
- Declares MCP server via tool config
- Parses `mcp_list_tools`, `mcp_call`, and `output_text` items
- Graceful fallback if MCP server unavailable

### 3. Intent Classifier (`app/llm/intent_classifier.py`)

Keyword-based classifier that routes messages:

- **Tool Mode triggers:** weather, temperature, currency, convert, USD, EUR, etc.
- **Ops Mode (default):** task, note, create, list, etc.

### 4. LLM Router (`app/llm/router.py`)

Service layer that:
- Classifies intent
- Routes to appropriate mode
- Returns unified response format

### 5. Configuration (`app/core/config.py`)

New settings:

```python
MCP_SERVER_URL: str = "http://mcp_http:8001/sse"
MCP_ENABLED: bool = True
```

## Docker Services

### `mcp` (STDIO mode - existing)
- Original FastMCP server
- Runs in STDIO mode
- Used for local/internal testing

### `mcp_http` (HTTP/SSE mode - new)
- HTTP bridge to FastMCP
- Port: 8001
- Accessible from Docker network
- Used by OpenAI Responses API

### `api`
- Updated with `MCP_SERVER_URL` environment variable
- Can access `mcp_http` service

## Available Tools

### 1. `weather_get`

Get current weather for a location.

**Parameters:**
- `city` (optional): City name
- `country` (optional): Country code
- `latitude` (optional): Latitude
- `longitude` (optional): Longitude

**Example:**
```json
{
  "name": "weather_get",
  "arguments": {
    "city": "London",
    "country": "GB"
  }
}
```

### 2. `fx_convert`

Convert currency (placeholder - not yet implemented).

**Parameters:**
- `base`: Base currency code
- `quote`: Quote currency code
- `amount`: Amount to convert

## Usage

### Starting the Services

```bash
# Start all services including MCP HTTP bridge
docker compose up -d

# Check MCP HTTP bridge health
curl http://localhost:8001/health

# List available tools
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

### Testing with Smoke Tests

```bash
# Run comprehensive smoke tests
python scripts/smoke_test_mcp.py

# Test against different URL
python scripts/smoke_test_mcp.py http://localhost:8001
```

### Using the Router in Code

```python
from app.llm.router import LlmRouterService

router = LlmRouterService()

# Will route to Tool Mode (weather query)
result = await router.process_message(
    messages_context=[{"role": "user", "content": "What's the weather in Paris?"}],
    tasks_snapshot=[],
)
# result["mode"] == "tool"
# result["text"] == "The current temperature in Paris is..."
# result["tool_calls"] == [{"name": "weather_get", ...}]

# Will route to Ops Mode (task management)
result = await router.process_message(
    messages_context=[{"role": "user", "content": "Create a task for tomorrow"}],
    tasks_snapshot=[],
)
# result["mode"] == "ops"
# result["proposal"] == LlmProposalPayload(...)
```

## Configuration

### Environment Variables

```bash
# Required for OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# MCP Configuration
MCP_SERVER_URL=http://mcp_http:8001/sse
MCP_ENABLED=true
```

### Docker Compose Override

To use external MCP server:

```yaml
services:
  api:
    environment:
      - MCP_SERVER_URL=https://external-mcp-server.com/sse
```

## Logging

All MCP operations are logged with structured logging:

```python
# Tool discovery
logger.info("mcp_tools_discovered", tool_count=2, tools=["weather_get", "fx_convert"])

# Tool execution
logger.info("mcp_tool_call_start", tool="weather_get", args={...})
logger.info("mcp_tool_call_complete", tool="weather_get", execution_time_ms=1234)

# Intent classification
logger.info("llm_router_intent_classified", intent="tool", message_preview="What's the weather...")
```

## Error Handling

### MCP Server Unavailable

If the MCP HTTP bridge is down:

1. Health check fails
2. Returns graceful message to user
3. No OpenAI API call made (saves costs)

```python
{
  "text": "MCP tool server is currently unavailable. Please try again later.",
  "tool_calls": []
}
```

### Tool Execution Errors

Errors during tool execution are caught and returned as MCP error responses:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "error": {
    "code": -32603,
    "message": "Tool execution failed: City not found"
  }
}
```

### OpenAI API Errors

Standard retry logic with exponential backoff (3 attempts).

## Extending with New Tools

### 1. Add Tool to FastMCP

```python
# app/mcp_server/tools/new_tool.py
from app.mcp_server.server import mcp

@mcp.tool
async def new_tool(param: str) -> dict:
    """Description of the tool."""
    return {"result": f"Processed {param}"}
```

### 2. Import in Server

```python
# app/mcp_server/server.py
from app.mcp_server.tools import new_tool  # noqa: F401
```

### 3. Update Intent Classifier (if needed)

```python
# app/llm/intent_classifier.py
TOOL_MODE_KEYWORDS = [
    # ... existing keywords
    r"\bnew_keyword\b",
]
```

### 4. Restart Services

```bash
docker compose restart mcp_http
```

## OpenAI MCP Format Reference

Based on: https://platform.openai.com/docs/guides/tools-connectors-mcp

### Tool Declaration

```python
tools = [
    {
        "type": "mcp",
        "server_label": "notex-mcp",
        "server_description": "Weather and FX tools",
        "server_url": "http://mcp_http:8001/sse",
        "require_approval": "never"  # or "always", "if_needed"
    }
]
```

### Response Items

- **`mcp_list_tools`** - Tool discovery phase
- **`mcp_call`** - Tool execution with name, arguments, result
- **`output_text`** - Final model response

## Troubleshooting

### Tools not discovered

```bash
# Check MCP HTTP bridge logs
docker compose logs mcp_http

# Test tools/list manually
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Tool execution fails

```bash
# Check tool registration
docker compose exec mcp_http python -c "from app.mcp_server.server import mcp; print(mcp._tools.keys())"

# Check tool implementation
docker compose logs mcp_http | grep "mcp_tool_call"
```

### Intent misclassified

Update keywords in `app/llm/intent_classifier.py` and restart services.

## Files Modified/Created

### New Files
- `app/mcp_server/http_bridge.py` - HTTP/SSE MCP bridge
- `app/llm/intent_classifier.py` - Intent classification
- `app/llm/router.py` - LLM routing service
- `scripts/smoke_test_mcp.py` - Smoke tests
- `MCP_INTEGRATION.md` - This documentation

### Modified Files
- `app/llm/openai_provider.py` - Added `generate_tool_response()` method
- `app/core/config.py` - Added `MCP_SERVER_URL` and `MCP_ENABLED`
- `docker-compose.yml` - Added `mcp_http` service

### Unchanged Files
- All existing ops-based proposal system files
- Task/note management logic
- Database models and repositories

## Next Steps

1. **Implement `fx_convert` tool** - Currently a placeholder
2. **Add more tools** - News, calendar, reminders, etc.
3. **Enhance intent classification** - ML-based classifier
4. **Add tool approval flow** - User confirmation for certain tools
5. **Metrics and monitoring** - Tool usage analytics
6. **Rate limiting** - Per-tool rate limits
7. **Caching** - Cache tool results (e.g., weather for 5 minutes)

## References

- [OpenAI Tools, Connectors, and MCP](https://platform.openai.com/docs/guides/tools-connectors-mcp)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
