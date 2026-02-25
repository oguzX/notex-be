# Notex - Chat-Driven Task Manager Backend

A production-ready FastAPI backend for a conversational task management system with realtime processing, LLM-powered task extraction, and event-driven architecture.

## Features

- **Chat-driven interface**: Natural language task management
- **LLM Integration**: OpenAI GPT and Google Gemini support
- **MCP Tool Mode**: Extensible tool calling via Model Context Protocol (weather, FX, and more)
- **Realtime Updates**: WebSocket and SSE for live event streaming
- **Latest-wins semantics**: Automatic stale proposal detection
- **Smart Resolution**: Natural language reference matching
- **Conflict Detection**: Scheduling conflict detection with resolution options
- **Audit Trail**: Complete task event history
- **Dockerized**: Full development environment
- **Production Ready**: Type hints, logging, error handling, tests

## Architecture

### Tech Stack

- **API**: FastAPI (async) with Python 3.12+
- **Database**: PostgreSQL 16 with SQLAlchemy 2.0 (async)
- **Cache/Queue**: Redis 7
- **Background Jobs**: Celery
- **Realtime**: WebSocket + SSE via Redis PubSub
- **LLM**: OpenAI Responses API or Google Gemini
- **MCP**: fastmcp for tool extension
- **Migrations**: Alembic
- **Code Quality**: Ruff, MyPy, pre-commit

### Core Flow

```
User Message → API → DB + Version Increment → Celery Task
                ↓
              Events (Redis PubSub + Streams)
                ↓
           WebSocket Broadcast

Celery Worker:
  1. Load context (messages + tasks)
  2. Classify intent (ops vs tool mode)
  3. Call LLM → Generate proposal or tool response
  4. Resolve natural references
  5. Check staleness + scheduling conflicts
  6. Auto-apply or wait for confirmation
  7. Publish events
```

### Data Models

- **Conversations**: Chat sessions with version tracking
- **Messages**: User/assistant messages (append-only)
- **Proposals**: LLM-generated task operations with resolution
- **Tasks**: To-do items with metadata
- **TaskEvents**: Immutable audit log
- **TaskAliases**: Natural language references

## Quick Start

### 1. Clone and setup

```bash
git clone <repo-url> && cd notex
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start services

```bash
docker compose up --build
```

This starts:
- **API** on `http://localhost:8000`
- **MCP HTTP bridge** on `http://localhost:8001`
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **Celery Worker** for background processing

### 3. Run migrations

```bash
docker compose exec api alembic upgrade head
```

### 4. Open API docs

- Swagger UI: http://localhost:8000/v1/docs
- Health check: http://localhost:8000/healthz

## API Endpoints

### Authentication

- `POST /register/guest` - Register guest user, returns access & refresh tokens
- `POST /auth/refresh` - Refresh tokens (rotates refresh token)

**Example: Register Guest**
```bash
curl -X POST http://localhost:8000/register/guest \
  -H "Content-Type: application/json" \
  -d '{"client_uuid": "550e8400-e29b-41d4-a716-446655440000"}'
```

**Response:**
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "abc123...",
  "token_type": "bearer",
  "expires_in": 900,
  "user_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

**All `/v1/*` endpoints require `Authorization: Bearer <access_token>`.**

### Conversations

- `POST /v1/conversations` - Create conversation
- `GET /v1/conversations/{id}` - Get conversation

### Messages

- `POST /v1/conversations/{id}/messages` - Send message
- `GET /v1/conversations/{id}/messages` - List messages

**Send Message Request Body:**
```json
{
  "content": "I have a meeting at 8pm tomorrow",
  "timezone": "Europe/Istanbul",
  "auto_apply": true
}
```

#### Idempotency

Supply `client_message_id` to prevent duplicate task creation from retries:

```bash
curl -X POST http://localhost:8000/v1/conversations/{id}/messages \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Schedule a call at 3pm",
    "client_message_id": "msg-abc-123-unique",
    "auto_apply": true
  }'
```

If retried with the same `client_message_id`, the response returns `"enqueued": false`.

### Tasks

- `GET /v1/tasks` - List all tasks for current user
- `GET /v1/conversations/{id}/tasks` - List tasks for a conversation

**Query Parameters:**
- `date_from` (optional): Filter tasks with `due_at >= YYYY-MM-DD`
- `date_to` (optional): Filter tasks with `due_at < day after YYYY-MM-DD`
- `status` (optional): `all` (default), `active`, `cancelled`

### Proposals

- `GET /v1/proposals/{id}` - Get proposal
- `GET /v1/conversations/{id}/proposals` - List proposals
- `POST /v1/proposals/{id}/confirm` - Confirm proposal (time or conflict resolution)
- `POST /v1/proposals/apply` - Manually apply proposal

### Realtime

- `WS /v1/ws/conversations/{id}` - WebSocket connection
- `GET /v1/conversations/{id}/events` - SSE stream (alternative)

## Confirmation Flows

### Time Confirmation

When `auto_apply=false` and no time is specified, the system returns `needs_confirmation` with suggested times:

```json
{
  "status": "needs_confirmation",
  "clarifications": [{
    "clarification_id": "clr_18d5f0c_abc123",
    "field": "due_at",
    "message": "When would you like to schedule 'Meeting tomorrow'?",
    "suggestions": [...]
  }]
}
```

Confirm with:
```bash
curl -X POST http://localhost:8000/v1/proposals/{id}/confirm \
  -H "Authorization: Bearer eyJhbGc..." \
  -d '{
    "updates": [{"clarification_id": "clr_18d5f0c_abc123", "due_at": "2026-01-30T20:00:00+03:00", "timezone": "Europe/Istanbul"}],
    "action": "apply"
  }'
```

### Conflict Resolution

When a new task conflicts with an existing one (within ±30 min), the system returns conflict info:

```json
{
  "status": "needs_confirmation",
  "clarifications": [{
    "field": "conflict",
    "message": "You already have 'Meet mom' at 07:00 PM. Do you want to cancel it?",
    "available_actions": ["replace_existing", "reschedule_new", "cancel_new"]
  }]
}
```

**Actions:**
- `replace_existing` — Cancel conflicting task, create new one
- `reschedule_new` — Set a new time for the proposed task
- `cancel_new` — Cancel the proposal entirely

## MCP Tool Integration

The system supports tool mode via Model Context Protocol for non-task queries (weather, currency conversion, etc.).

Intent is classified automatically:
- "What's the weather in Paris?" → **Tool mode**
- "Create a task for tomorrow" → **Ops mode**

See [MCP_QUICKSTART.md](MCP_QUICKSTART.md) for setup and available tools.

## Event Types

| Event | Description |
|-------|-------------|
| `message.received` | User message stored |
| `llm.queued` | Processing job enqueued |
| `llm.running` | LLM generating proposal |
| `proposal.ready` | Proposal ready to apply |
| `proposal.needs_confirmation` | Missing time or conflict detected |
| `proposal.applied` | Operations executed |
| `proposal.stale` | Newer version exists |
| `proposal.failed` | Processing error |
| `proposal.canceled` | User canceled the proposal |
| `tasks.changed` | Tasks modified |

## Environment Variables

Copy `.env.example` to `.env` and fill in values.

**Required:**
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `CELERY_BROKER_URL` | Celery broker (Redis) |
| `CELERY_RESULT_BACKEND` | Celery result backend (Redis) |

**LLM:**
| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openai` | `openai` or `gemini` |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `GEMINI_API_KEY` | — | Gemini API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | Gemini model |

**Auth:**
| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | insecure default | Secret key — **change in production** |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | 15 minutes |
| `REFRESH_TOKEN_TTL_SECONDS` | `2592000` | 30 days |

**MCP:**
| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_ENABLED` | `true` | Enable MCP tool mode |
| `MCP_SERVER_URL` | `http://mcp_http:8001/sse` | MCP server endpoint |

**Other:**
| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level |
| `RESOLVER_CONFIDENCE_THRESHOLD` | `0.65` | Min score for auto-resolution |
| `NOTIFICATIONS_ENABLED` | `true` | Enable push notifications |
| `ONESIGNAL_APP_ID` | — | OneSignal app ID |
| `ONESIGNAL_REST_API_KEY` | — | OneSignal REST API key |

## Development

### Local Setup

```bash
# Install dependencies
pip install -e ".[dev]"

# Setup pre-commit hooks
pre-commit install

# Copy env file
cp .env.example .env

# Start services
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head
```

### Makefile Commands

```bash
make up           # Start all services
make down         # Stop all services
make logs         # Follow logs
make test         # Run tests
make format       # Format code (ruff)
make lint         # Lint code
make type-check   # MyPy type check
make alembic-upgrade  # Run migrations
```

### Running Locally (without Docker)

```bash
# API
uvicorn app.main:app --reload

# Worker
celery -A app.workers.celery_app worker --loglevel=info
```

### Code Quality

```bash
make format       # ruff format + fix
make lint         # ruff check
make type-check   # mypy
```

## Project Structure

```
app/
├── core/          # Config, logging, middleware, errors
├── db/            # Models, repositories, session
├── schemas/       # Pydantic models
├── services/      # Business logic
├── llm/           # LLM providers, router, intent classifier
├── mcp_server/    # MCP server + HTTP bridge
├── events/        # Event bus, PubSub, Streams, WebSocket
├── workers/       # Celery tasks
├── routes/        # API endpoints
├── auth/          # JWT authentication
├── notifications/ # Push notification integration
└── utils/         # Helpers (time, similarity, IDs)
```

## Testing

```bash
# Run all tests
pytest

# With coverage report
pytest --cov=app --cov-report=html

# Specific test file
pytest tests/test_resolver.py -v
```

## Deployment

### Docker Compose

```bash
docker compose up -d
```

### Production Checklist

- Set `ENV=production`
- Set a strong `JWT_SECRET`
- Configure production database credentials
- Set `LOG_FORMAT=json`
- Configure LLM API keys
- Set up push notifications (OneSignal) if needed

## License

MIT
