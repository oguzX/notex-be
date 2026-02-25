# File Summary

Quick reference for the codebase structure and responsibilities.

## Core (`app/core/`)

- **config.py**: Pydantic settings with env var loading
- **logging.py**: Structured logging with structlog
- **middleware.py**: Request ID middleware for tracing
- **errors.py**: Custom exceptions and global error handlers

## Database (`app/db/`)

### Models (`app/db/models/`)

- **conversation.py**: Chat session with version tracking
- **message.py**: User/assistant messages
- **proposal.py**: LLM-generated task operations
- **task.py**: To-do items with soft delete
- **task_event.py**: Immutable audit log
- **task_alias.py**: Natural language references

### Repositories (`app/db/repositories/`)

- **conversation_repo.py**: CRUD + version increment
- **message_repo.py**: Message storage and context retrieval
- **proposal_repo.py**: Proposal lifecycle management
- **task_repo.py**: Task CRUD + time window search
- **task_event_repo.py**: Event logging

### Infrastructure

- **base.py**: SQLAlchemy declarative base
- **session.py**: Async session factory and dependency

## Schemas (`app/schemas/`)

- **enums.py**: All enum types
- **messages.py**: Message request/response models
- **proposals.py**: Proposal payloads and resolution
- **tasks.py**: Task and event responses
- **events.py**: WebSocket event schemas

## Services (`app/services/`)

- **conversations_service.py**: Conversation CRUD
- **messages_service.py**: Message creation + Celery enqueue
- **tasks_service.py**: Task listing
- **proposals_service.py**: Proposal application + operation execution
- **resolver_service.py**: Natural reference → task ID resolution

## LLM (`app/llm/`)

- **base.py**: Provider interface
- **factory.py**: Provider selection by config
- **openai_provider.py**: OpenAI GPT integration
- **gemini_provider.py**: Google Gemini integration
- **prompts.py**: System prompt templates

## Events (`app/events/`)

- **bus.py**: Unified event bus (PubSub + Streams)
- **redis_pubsub.py**: Realtime event broadcasting
- **redis_streams.py**: Persistent event storage
- **websocket_manager.py**: WebSocket connection manager

## Workers (`app/workers/`)

- **celery_app.py**: Celery configuration
- **tasks.py**: Message processing task (LLM → resolution → apply)

## Routes (`app/routes/`)

- **health.py**: Health check endpoints
- **conversations.py**: Conversation endpoints
- **messages.py**: Message endpoints
- **tasks.py**: Task endpoints
- **proposals.py**: Proposal endpoints
- **realtime.py**: WebSocket and SSE endpoints

## Utils (`app/utils/`)

- **ids.py**: UUID generation
- **time.py**: Natural language time parsing
- **json.py**: Custom JSON encoder
- **similarity.py**: Text similarity scoring

## Root Files

- **main.py**: FastAPI app with lifespan, routes, middleware
- **Dockerfile**: Multi-stage container build
- **docker-compose.yml**: Full dev environment
- **alembic.ini**: Migration configuration
- **alembic/env.py**: Async migration runner
- **alembic/versions/0001_initial.py**: Initial schema
- **pyproject.toml**: Dependencies and tool config
- **Makefile**: Development commands

## Key Patterns

### Repository Pattern
Thin data access layer - DB queries only.

### Service Layer
Business logic orchestration - transactions, validation, events.

### Event-Driven
Every state change publishes events to Redis.

### Latest-Wins
Version checking prevents stale operations from applying.

### Resolver
Deterministic scoring: time proximity + text similarity + recency.
