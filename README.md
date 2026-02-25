# Notex - Chat-Driven Task Manager Backend

A production-ready FastAPI backend for a conversational task management system with realtime processing, LLM-powered task extraction, and event-driven architecture.

## Features

- 💬 **Chat-driven interface**: Natural language task management
- 🤖 **LLM Integration**: OpenAI GPT and Google Gemini support
- ⚡ **Realtime Updates**: WebSocket and SSE for live event streaming
- 🔄 **Latest-wins semantics**: Automatic stale proposal detection
- 🎯 **Smart Resolution**: Natural language reference matching
- 📝 **Audit Trail**: Complete task event history
- 🐳 **Dockerized**: Full development environment
- ✅ **Production Ready**: Type hints, logging, error handling, tests

## Architecture

### Tech Stack

- **API**: FastAPI (async) with Python 3.12
- **Database**: PostgreSQL 16 with SQLAlchemy 2.0 (async)
- **Cache/Queue**: Redis 7
- **Background Jobs**: Celery
- **Realtime**: WebSocket + SSE via Redis PubSub
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
  2. Call LLM → Generate proposal
  3. Resolve natural references
  4. Check staleness
  5. Auto-apply or wait for confirmation
  6. Publish events
```

### Data Models

- **Conversations**: Chat sessions with version tracking
- **Messages**: User/assistant messages (append-only)
- **Proposals**: LLM-generated task operations with resolution
- **Tasks**: To-do items with metadata
- **TaskEvents**: Immutable audit log
- **TaskAliases**: Natural language references

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

**Example: Use Access Token**
```bash
curl -X POST http://localhost:8000/v1/conversations \
  -H "Authorization: Bearer eyJhbGc..."
```

**Example: Refresh Token**
```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "abc123..."}'
```

### Conversations

- `POST /v1/conversations` - Create conversation (requires auth)
- `GET /v1/conversations/{id}` - Get conversation (requires auth, ownership checked)

### Messages

- `POST /v1/conversations/{id}/messages` - Send message (requires auth, ownership checked)
- `GET /v1/conversations/{id}/messages` - List messages (requires auth, ownership checked)

**Send Message Request Body:**
```json
{
  "content": "I have a meeting at 8pm tomorrow",
  "timezone": "Europe/Istanbul",
  "auto_apply": true
}
```

#### Idempotency

The Messages API supports optional idempotency via `client_message_id`. If you provide this field:

- If a message with the same `(conversation_id, client_message_id)` already exists, the API returns the existing message without creating a duplicate or re-enqueuing processing.
- This prevents duplicate task creation from accidental retries (network issues, double-taps).

**Example with idempotency key:**
```bash
curl -X POST http://localhost:8000/v1/conversations/{id}/messages \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: req-123" \
  -d '{
    "content": "Schedule a call at 3pm",
    "client_message_id": "msg-abc-123-unique",
    "auto_apply": true
  }'
```

If the request is retried with the same `client_message_id`, the response will return `"enqueued": false` indicating no new processing was triggered.

### Tasks

- `GET /v1/tasks` - List all tasks for current user across all conversations (requires auth)
- `GET /v1/conversations/{id}/tasks` - List tasks for a conversation (requires auth, ownership checked)

**List All Tasks Query Parameters:**
- `date_from` (optional): Filter tasks with due_at >= this date (YYYY-MM-DD)
- `date_to` (optional): Filter tasks with due_at < day after this date (YYYY-MM-DD)
- `status` (optional): Filter by status: `all` (default), `active`, `cancelled`

**Example: List All User Tasks**
```bash
curl -X GET "http://localhost:8000/v1/tasks?date_from=2026-01-01&date_to=2026-01-31&status=active" \
  -H "Authorization: Bearer eyJhbGc..."
```

### Proposals

- `GET /v1/proposals/{id}` - Get proposal (requires auth, ownership checked)
- `GET /v1/conversations/{id}/proposals` - List proposals (requires auth, ownership checked)
- `POST /v1/proposals/apply` - Manually apply proposal (requires auth, ownership checked)
- `POST /v1/proposals/{id}/confirm-time` - Confirm time for proposal requiring time clarification

### Realtime

- `WS /v1/ws/conversations/{id}` - WebSocket connection
- `GET /v1/conversations/{id}/events` - SSE stream (alternative)

**Note**: All `/v1/*` endpoints require authentication via `Authorization: Bearer <access_token>` header.
Accessing resources belonging to other users returns `403 Forbidden`.

## Time Confirmation Flow

When `auto_apply=false` and a user message implies creating a task without specifying a time, the system:

1. Returns the proposal with status `needs_confirmation`
2. Includes `clarifications` with suggested times
3. Requires confirmation via `POST /v1/proposals/{id}/confirm-time` before applying

**Example: Send Message with auto_apply=false**
```bash
curl -X POST http://localhost:8000/v1/conversations/{id}/messages \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Add a meeting tomorrow",
    "auto_apply": false,
    "timezone": "Europe/Istanbul"
  }'
```

**Response with needs_confirmation:**
```json
{
  "id": "msg-123",
  "proposal_id": "prop-456",
  "status": "needs_confirmation",
  "ops": {
    "ops": [{
      "op": "create",
      "temp_id": "task_1",
      "title": "Meeting tomorrow",
      "due_at": null
    }],
    "needs_confirmation": true,
    "clarifications": [{
      "field": "due_at",
      "op_ref": {"type": "temp_id", "value": "task_1"},
      "message": "When would you like to schedule 'Meeting tomorrow'?",
      "suggestions": [{
        "due_at": "2026-01-30T19:00:00+03:00",
        "timezone": "Europe/Istanbul",
        "label": "Tomorrow evening at 7 PM (suggested)",
        "confidence": 0.7
      }]
    }]
  }
}
```

**Confirm Time:**
```bash
curl -X POST http://localhost:8000/v1/proposals/prop-456/confirm-time \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{
    "updates": [{
      "ref": {"type": "temp_id", "value": "task_1"},
      "due_at": "2026-01-30T20:00:00+03:00",
      "timezone": "Europe/Istanbul"
    }]
  }'
```

**Response:**
```json
{
  "proposal_id": "prop-456",
  "applied": true,
  "tasks_affected": 1
}
```

## Conflict-Aware Confirmation Flow

The system detects scheduling conflicts when creating tasks at times that overlap with existing tasks (within ±30 minutes).

### Scenario Example

1. User creates a task: "meet my mom at 7 PM" → Task created at 19:00
2. Later, user says: "we will meet friends at 7 PM" (same time)
3. System detects conflict and asks user to choose:
   - **Replace existing**: Cancel old task, create new task at the requested time
   - **Reschedule new**: Choose a different time for the new task
   - **Cancel new**: Cancel the new task entirely

### New Confirm Endpoint

`POST /v1/proposals/{proposal_id}/confirm`

This is the primary endpoint for confirming proposals with time updates or conflict resolution.

**Request Body:**
```json
{
  "updates": [
    {
      "clarification_id": "clr_123abc...",
      "due_at": "2026-01-29T20:00:00Z",
      "timezone": "UTC"
    }
  ],
  "action": "apply" | "replace_existing" | "reschedule_new" | "cancel_new"
}
```

**Actions:**
- `apply`: Apply proposal if no conflicts (or fill in due_at for missing times)
- `replace_existing`: Cancel the conflicting existing task and create the new one
- `reschedule_new`: Update the new task's time and re-check for conflicts
- `cancel_new`: Cancel the proposal entirely (no new task created)

### Example: Conflict Detected

When a proposal has a scheduling conflict, the response includes:

```json
{
  "id": "prop-789",
  "status": "needs_confirmation",
  "ops": {
    "ops": [{
      "op": "create",
      "temp_id": "task_1",
      "title": "Meet friends",
      "due_at": "2026-01-29T19:00:00Z"
    }],
    "needs_confirmation": true,
    "clarifications": [{
      "clarification_id": "clr_18d5f0c_abc123",
      "field": "conflict",
      "target_temp_id": "task_1",
      "message": "You already have 'Meet mom' at 07:00 PM. Do you want to cancel it and schedule 'Meet friends'?",
      "suggestions": [
        {
          "due_at": "2026-01-29T20:00:00Z",
          "timezone": "UTC",
          "label": "08:00 PM (1 hour later)",
          "confidence": 0.7
        },
        {
          "due_at": "2026-01-29T20:30:00Z",
          "timezone": "UTC",
          "label": "08:30 PM (1.5 hours later)",
          "confidence": 0.7
        }
      ],
      "context": {
        "upcoming_tasks": [
          {
            "task_id": "existing-task-uuid",
            "conversation_id": "conv-uuid",
            "title": "Meet mom",
            "due_at": "2026-01-29T19:00:00Z",
            "status": "active"
          }
        ],
        "window_start": "2026-01-29T16:00:00Z",
        "window_end": "2026-01-29T22:00:00Z"
      },
      "conflict": {
        "existing_task": {
          "task_id": "existing-task-uuid",
          "conversation_id": "conv-uuid",
          "title": "Meet mom",
          "due_at": "2026-01-29T19:00:00Z",
          "status": "active"
        },
        "proposed_due_at": "2026-01-29T19:00:00Z",
        "window_minutes": 30
      },
      "available_actions": ["replace_existing", "reschedule_new", "cancel_new"]
    }]
  }
}
```

### Example: Replace Existing Task

```bash
curl -X POST http://localhost:8000/v1/proposals/prop-789/confirm \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{
    "updates": [],
    "action": "replace_existing"
  }'
```

**Response:**
```json
{
  "proposal_id": "prop-789",
  "status": "applied",
  "applied": true,
  "tasks_affected": 1,
  "tasks_canceled": 1,
  "needs_further_confirmation": false
}
```

### Example: Reschedule to Alternative Time

```bash
curl -X POST http://localhost:8000/v1/proposals/prop-789/confirm \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{
    "updates": [{
      "clarification_id": "clr_18d5f0c_abc123",
      "due_at": "2026-01-29T20:00:00Z",
      "timezone": "UTC"
    }],
    "action": "reschedule_new"
  }'
```

**Response (if new time is conflict-free):**
```json
{
  "proposal_id": "prop-789",
  "status": "applied",
  "applied": true,
  "tasks_affected": 1,
  "tasks_canceled": 0,
  "needs_further_confirmation": false
}
```

**Response (if new time also has conflicts):**
```json
{
  "proposal_id": "prop-789",
  "status": "needs_confirmation",
  "applied": false,
  "tasks_affected": 0,
  "needs_further_confirmation": true,
  "clarifications": [
    {
      "clarification_id": "clr_18d5f0d_def456",
      "field": "conflict",
      "message": "'Meet friends' at 08:00 PM conflicts with 'Another task'",
      "available_actions": ["replace_existing", "reschedule_new", "cancel_new"]
    }
  ]
}
```

### Example: Cancel New Task

```bash
curl -X POST http://localhost:8000/v1/proposals/prop-789/confirm \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{
    "updates": [],
    "action": "cancel_new"
  }'
```

**Response:**
```json
{
  "proposal_id": "prop-789",
  "status": "canceled",
  "applied": false,
  "tasks_affected": 0,
  "tasks_canceled": 0,
  "needs_further_confirmation": false
}
```

### Clarification Reference by ID

The new confirm endpoint uses `clarification_id` to reference specific clarifications, simplifying the API:

**Old approach (deprecated):**
```json
{
  "updates": [{
    "ref": {"type": "temp_id", "value": "task_1"},
    "due_at": "..."
  }]
}
```

**New approach:**
```json
{
  "updates": [{
    "clarification_id": "clr_18d5f0c_abc123",
    "due_at": "..."
  }]
}
```

The server generates a stable `clarification_id` for each clarification, which is returned in the proposal response and used to reference it in the confirm request.

## Event Types

- `message.received` - User message stored
- `llm.queued` - Processing job enqueued
- `llm.running` - LLM generating proposal
- `proposal.ready` - Proposal ready to apply
- `proposal.needs_confirmation` - Missing time or conflict detected
- `proposal.applied` - Operations executed
- `proposal.stale` - Newer version exists
- `proposal.failed` - Processing error
- `proposal.canceled` - User canceled the proposal
- `tasks.changed` - Tasks modified

## Environment Variables

See [.env.example](.env.example) for all options.

**Required**:
- `DATABASE_URL`: PostgreSQL connection
- `REDIS_URL`: Redis connection
- `CELERY_BROKER_URL`: Celery broker
- `CELERY_RESULT_BACKEND`: Celery results

**Optional**:
- `LLM_PROVIDER`: `openai` or `gemini` (default: openai)
- `OPENAI_API_KEY`: OpenAI API key (mock mode if not set)
- `GEMINI_API_KEY`: Gemini API key (mock mode if not set)
- `JWT_SECRET`: Secret key for JWT signing (default: insecure, change in production)
- `ACCESS_TOKEN_TTL_SECONDS`: Access token lifetime (default: 900 = 15 minutes)
- `REFRESH_TOKEN_TTL_SECONDS`: Refresh token lifetime (default: 2592000 = 30 days)
- `LOG_LEVEL`: Logging level
- `RESOLVER_CONFIDENCE_THRESHOLD`: Min score for auto-resolution (default: 0.65)

## Development

### Local Setup

```bash
# Install dependencies
pip install -e ".[dev]"

# Setup pre-commit
pre-commit install

# Copy env file
cp .env.example .env

# Start services
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head
```

### Running Services

```bash
# All services
make up

# View logs
make logs

# API only (with auto-reload)
uvicorn app.main:app --reload

# Worker only
celery -A app.workers.celery_app worker --loglevel=info
```

### Code Quality

```bash
# Format code
make format

# Lint
make lint

# Type check
make type-check

# Run tests
make test
```

## Project Structure

```
app/
├── core/          # Config, logging, middleware, errors
├── db/            # Models, repositories, session
├── schemas/       # Pydantic models
├── services/      # Business logic
├── llm/           # LLM provider implementations
├── events/        # Event bus, PubSub, Streams, WebSocket
├── workers/       # Celery tasks
├── routes/        # API endpoints
└── utils/         # Helpers (time, similarity, IDs)
```

See [FILE_SUMMARY.md](FILE_SUMMARY.md) for detailed module descriptions.

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Specific test
pytest tests/test_resolver.py -v
```

## Deployment

### Docker Compose (Production)

```bash
docker compose -f docker-compose.yml up -d
```

### Environment

Set `ENV=production` and configure:
- Secure database credentials
- Production Redis instance
- API keys for LLM providers
- `LOG_FORMAT=json`

## Troubleshooting

See [DEBUGGING_CHECKLIST.md](DEBUGGING_CHECKLIST.md)

## License

MIT
# notex-be
