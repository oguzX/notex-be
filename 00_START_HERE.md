# 🚀 Quick Start Guide

Welcome to **Notex** - the chat-driven task manager backend!

## Prerequisites

- Docker and Docker Compose
- (Optional) Python 3.12+ for local development

## 5-Minute Setup

### 1. Clone and Setup

```bash
cd Notex
cp .env.example .env
```

### 2. Start Services

```bash
docker compose up --build
```

This starts:
- **API** on `http://localhost:8000`
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **Celery Worker** for background processing

### 3. Run Migrations

In a new terminal:

```bash
docker compose exec api alembic upgrade head
```

### 4. Test the API

Open your browser:
- **API Docs**: http://localhost:8000/v1/docs
- **Health Check**: http://localhost:8000/healthz

### 5. Test WebSocket Connection

Use the Swagger UI at `/v1/docs`:

1. **Create a conversation**:
   ```
   POST /v1/conversations
   Body: {"user_id": "00000000-0000-0000-0000-000000000001"}
   ```

2. **Connect WebSocket**:
   - WebSocket URL: `ws://localhost:8000/v1/ws/conversations/{conversation_id}`
   - Use a WebSocket client or the browser console

3. **Send a message**:
   ```
   POST /v1/conversations/{conversation_id}/messages
   Body: {
     "content": "I have a meeting at 8pm tomorrow",
     "auto_apply": true
   }
   ```

4. **Watch events** flow through the WebSocket:
   - `message.received`
   - `llm.queued`
   - `llm.running`
   - `proposal.ready`
   - `proposal.applied`
   - `tasks.changed`

## Using the Makefile

```bash
# Start services
make up

# View logs
make logs

# Run migrations
make alembic-upgrade

# Stop services
make down

# Run tests
make test

# Format code
make format
```

## Next Steps

- Read [README.md](README.md) for architecture details
- Check [FILE_SUMMARY.md](FILE_SUMMARY.md) for module descriptions
- See [DEBUGGING_CHECKLIST.md](DEBUGGING_CHECKLIST.md) if you run into issues

## Common Commands

```bash
# Shell into API container
docker compose exec api bash

# View worker logs
docker compose logs -f worker

# PostgreSQL shell
docker compose exec db psql -U notex -d notex

# Redis CLI
docker compose exec redis redis-cli
```

Enjoy building with Notex! 🎉
