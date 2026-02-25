# MCP Integration - Quick Start Guide

## 🚀 Get Started in 3 Minutes

### 1. Update Docker Compose (Already Done ✅)

The following service has been added to your `docker-compose.yml`:

```yaml
mcp_http:
  ports:
    - "8001:8001"
  command: ["uvicorn", "app.mcp_server.http_bridge:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
```

### 2. Set Environment Variables

Ensure your `.env` or environment includes:

```bash
OPENAI_API_KEY=sk-...           # Required for OpenAI
OPENAI_MODEL=gpt-4o             # Default model
MCP_SERVER_URL=http://mcp_http:8001/sse  # Already configured
MCP_ENABLED=true                # Already configured
```

### 3. Start Services

```bash
# Start all services including the new mcp_http service
docker compose up -d

# Verify services are running
docker compose ps

# Check MCP HTTP bridge is healthy
curl http://localhost:8001/health
```

### 4. Run Smoke Tests

```bash
# Quick test script
./scripts/test_mcp_endpoints.sh

# Comprehensive Python smoke tests
python scripts/smoke_test_mcp.py
```

Expected output:
```
✅ Health check passed
✅ Tools list returned 2 tools: weather_get, fx_convert
✅ Tool call succeeded
✅ All intent classification tests passed
✅ All smoke tests passed!
```

---

## 📚 How It Works

### Example 1: Tool Mode (Weather Query)

**User:** "What's the weather in London?"

**Flow:**
1. Intent classifier detects "weather" keyword → **Tool Mode**
2. OpenAI Responses API called with MCP tool config
3. MCP server lists available tools (`weather_get`, `fx_convert`)
4. Model decides to call `weather_get` with args `{city: "London", country: "GB"}`
5. MCP server executes tool and returns weather data
6. Model generates natural language response with weather info

**Response:**
```json
{
  "mode": "tool",
  "text": "The current temperature in London is 12°C with 75% humidity and 15 km/h winds.",
  "tool_calls": [
    {
      "name": "weather_get",
      "arguments": {"city": "London", "country": "GB"},
      "result": {...}
    }
  ]
}
```

### Example 2: Ops Mode (Task Management)

**User:** "Create a task to review the report tomorrow"

**Flow:**
1. Intent classifier → **Ops Mode** (default, no tool keywords)
2. Traditional `generate_proposal()` method called
3. Returns JSON operations for task creation
4. Existing proposal system processes as normal

**Response:**
```json
{
  "mode": "ops",
  "proposal": {
    "ops": [
      {
        "op": "create",
        "type": "task",
        "title": "Review the report",
        ...
      }
    ],
    "reasoning": "Creating task for tomorrow"
  }
}
```

---

## 🛠️ Testing Endpoints Manually

### Health Check
```bash
curl http://localhost:8001/health
```

### List Available Tools
```bash
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | jq .
```

### Call Weather Tool
```bash
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "weather_get",
      "arguments": {
        "city": "Paris",
        "country": "FR"
      }
    }
  }' | jq .
```

---

## 📖 Integration in Your Code

### Option 1: Use the Router (Recommended)

```python
from app.llm.router import LlmRouterService

router = LlmRouterService()

# Automatically routes based on intent
result = await router.process_message(
    messages_context=[
        {"role": "user", "content": "What's the weather in Tokyo?"}
    ],
    tasks_snapshot=[],
)

if result["mode"] == "tool":
    # Tool mode response
    print(result["text"])  # Natural language response
    print(result["tool_calls"])  # List of tool executions
else:
    # Ops mode response
    proposal = result["proposal"]  # LlmProposalPayload
    # Process proposal as usual
```

### Option 2: Direct Provider Access

```python
from app.llm.factory import get_llm_provider

provider = get_llm_provider()  # Returns OpenAIProvider or GeminiProvider

# For weather/FX queries - Tool Mode
result = await provider.generate_tool_response(
    messages_context=[
        {"role": "user", "content": "What's the weather in Paris?"}
    ]
)

# For task management - Ops Mode (unchanged)
proposal = await provider.generate_proposal(
    messages_context=[...],
    tasks_snapshot=[...],
    timezone="UTC",
)
```

---

## 🔍 Monitoring & Logs

### View MCP HTTP Bridge Logs
```bash
docker compose logs -f mcp_http
```

**Key Log Events:**
- `mcp_request` - Incoming MCP request
- `mcp_tools_listed` - Tool discovery
- `mcp_tool_call_start` - Tool execution begins
- `mcp_tool_call_complete` - Tool execution ends with timing

### View API Service Logs
```bash
docker compose logs -f api
```

**Key Log Events:**
- `llm_router_intent_classified` - Intent classification result
- `openai_mcp_request_start` - OpenAI Responses API call
- `mcp_tools_discovered` - Tools imported from MCP
- `mcp_tool_executed` - Tool called by model
- `openai_mcp_response_received` - Response with token usage

---

## 🐛 Troubleshooting

### MCP Server Not Starting

**Issue:** `mcp_http` service fails to start

**Check:**
```bash
docker compose logs mcp_http
```

**Common Causes:**
- Port 8001 already in use
- Missing dependencies (sse-starlette)

**Fix:**
```bash
# Change port in docker-compose.yml
ports:
  - "8002:8001"

# And update MCP_SERVER_URL
environment:
  - MCP_SERVER_URL=http://mcp_http:8001/sse
```

### Tools Not Being Called

**Issue:** Model doesn't use tools even for weather queries

**Check:**
1. Verify MCP server is accessible:
   ```bash
   curl http://localhost:8001/health
   ```

2. Check intent classification:
   ```python
   from app.llm.intent_classifier import classify_intent
   result = classify_intent("What's the weather?")
   print(result)  # Should be IntentType.TOOL_MODE
   ```

3. Verify OpenAI API key is valid:
   ```bash
   echo $OPENAI_API_KEY
   ```

### "Tool Mode Unavailable" Message

**Issue:** System returns "MCP tool mode is currently disabled"

**Check:**
```bash
# Verify environment variable
docker compose exec api python -c "from app.core.config import get_settings; print(get_settings().MCP_ENABLED)"
```

**Fix:**
```bash
# In .env or docker-compose.yml
MCP_ENABLED=true
```

---

## 📝 Available Tools

### 1. weather_get

Get current weather for a location.

**Parameters:**
- `city` (optional): City name
- `country` (optional): Country code (ISO 3166-1 alpha-2)
- `latitude` (optional): Latitude coordinate
- `longitude` (optional): Longitude coordinate

**Examples:**
- By city: `{"city": "London", "country": "GB"}`
- By coordinates: `{"latitude": 51.5074, "longitude": -0.1278}`

### 2. fx_convert

Currency conversion (placeholder - not yet implemented).

**Parameters:**
- `base`: Base currency code (e.g., "USD")
- `quote`: Quote currency code (e.g., "EUR")
- `amount`: Amount to convert

---

## 🎯 Intent Classification Examples

| Message | Mode | Reason |
|---------|------|--------|
| "What's the weather in Paris?" | **Tool** | Contains "weather" |
| "Show me temperature in London" | **Tool** | Contains "temperature" |
| "Convert 100 USD to EUR" | **Tool** | Contains "convert" and "USD" |
| "Exchange rate for GBP" | **Tool** | Contains "exchange" and "GBP" |
| "Create a task for tomorrow" | **Ops** | No tool keywords |
| "Add a note about the meeting" | **Ops** | No tool keywords |
| "List all my tasks" | **Ops** | No tool keywords |

---

## 🔧 Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | None | OpenAI API key (**required**) |
| `OPENAI_MODEL` | `gpt-4o` | Model for Responses API |
| `MCP_SERVER_URL` | `http://mcp_http:8001/sse` | MCP server endpoint |
| `MCP_ENABLED` | `true` | Enable/disable MCP tool mode |

---

## 📦 What's Unchanged

✅ **Task Management** - All existing task/note operations work exactly as before  
✅ **Proposal System** - Ops generation unchanged  
✅ **Database Models** - No schema changes  
✅ **API Endpoints** - No breaking changes  
✅ **Frontend Integration** - Existing integrations continue to work

The MCP integration is **purely additive** - your existing system remains 100% functional.

---

## 🎉 You're Ready!

Your MCP integration is now active. Try these queries:

**Tool Mode:**
- "What's the weather in Tokyo?"
- "Show me the temperature in New York"
- "Convert 100 USD to EUR"

**Ops Mode (unchanged):**
- "Create a task to review the report"
- "Add a note about the meeting"
- "List all my tasks"

For detailed documentation, see:
- [MCP_INTEGRATION.md](./MCP_INTEGRATION.md) - Full documentation
- [MCP_IMPLEMENTATION_SUMMARY.md](./MCP_IMPLEMENTATION_SUMMARY.md) - Implementation details

Happy building! 🚀
