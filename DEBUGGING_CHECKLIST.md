# Debugging Checklist

Common issues and solutions when working with Notex.

## Services Not Starting

### Docker Compose Issues

**Symptom**: Services fail to start or crash immediately

**Checks**:
```bash
# Check if ports are already in use
lsof -i :8000  # API
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis

# Check logs
docker compose logs api
docker compose logs worker
docker compose logs db
docker compose logs redis

# Rebuild containers
docker compose down -v
docker compose up --build
```

**Common Causes**:
- Port conflicts (change ports in docker-compose.yml)
- Volume permission issues (remove volumes with `docker compose down -v`)
- Missing `.env` file (copy from `.env.example`)

## Database Issues

### Migration Errors

**Symptom**: Alembic migration fails

**Checks**:
```bash
# Check current migration state
docker compose exec api alembic current

# Check database connection
docker compose exec api python -c "from app.db.session import init_db; import asyncio; asyncio.run(init_db())"

# Reset database (WARNING: destroys data)
docker compose down -v
docker compose up -d db
docker compose exec api alembic upgrade head
```

**Common Causes**:
- Database not initialized (run `alembic upgrade head`)
- Alembic version table corrupted (drop `alembic_version` table)
- Wrong DATABASE_URL in .env

### Connection Pool Exhausted

**Symptom**: "QueuePool limit of size X overflow Y reached"

**Fix**: Increase pool size in `app/core/config.py`:
```python
DB_POOL_SIZE: int = 20
DB_MAX_OVERFLOW: int = 40
```

## Redis Issues

### Connection Refused

**Symptom**: "Error connecting to Redis"

**Checks**:
```bash
# Test Redis connection
docker compose exec redis redis-cli ping
# Should return PONG

# Check Redis logs
docker compose logs redis

# Test from API container
docker compose exec api python -c "import redis; r = redis.from_url('redis://redis:6379/0'); print(r.ping())"
```

**Common Causes**:
- Redis not started (check `docker compose ps`)
- Wrong REDIS_URL in .env (should be `redis://redis:6379/0` in Docker)

## Celery Worker Issues

### Worker Not Processing Tasks

**Symptom**: Messages enqueued but not processed

**Checks**:
```bash
# Check worker is running
docker compose ps worker

# Check worker logs
docker compose logs -f worker

# Check Celery broker connection
docker compose exec worker python -c "from app.workers.celery_app import celery_app; print(celery_app.control.inspect().stats())"

# Check queues
docker compose exec redis redis-cli KEYS "celery*"
```

**Common Causes**:
- Worker not started (check logs for startup errors)
- Wrong CELERY_BROKER_URL (should match Redis URL)
- Task not registered (check imports in `celery_app.py`)

### Task Timeout

**Symptom**: Tasks fail with "SoftTimeLimitExceeded"

**Fix**: Increase timeout in `app/core/config.py`:
```python
CELERY_TASK_TIME_LIMIT: int = 600  # 10 minutes
CELERY_TASK_SOFT_TIME_LIMIT: int = 570
```

## WebSocket Issues

### Connection Not Receiving Events

**Symptom**: WebSocket connects but no events arrive

**Checks**:
```bash
# Check if events are being published
docker compose logs -f worker

# Check Redis PubSub
docker compose exec redis redis-cli
# In redis-cli:
> PUBSUB CHANNELS events:*
> SUBSCRIBE events:{conversation_id}

# Check WebSocket manager logs
docker compose logs -f api | grep websocket
```

**Common Causes**:
- Wrong conversation ID in WebSocket URL
- Events published before WebSocket connected (use event history)
- Redis PubSub not working (restart Redis)

### WebSocket Disconnects Immediately

**Symptom**: Connection closes right after opening

**Checks**:
- Check CORS settings if connecting from browser
- Check API logs for errors
- Verify URL format: `ws://localhost:8000/v1/ws/conversations/{id}`

## LLM Integration Issues

### Mock Responses Only

**Symptom**: Always getting mock/demo proposals

**Checks**:
```bash
# Check if API key is set
docker compose exec api env | grep API_KEY

# Check provider logs
docker compose logs -f worker | grep llm
```

**Common Causes**:
- API key not set in .env
- OpenAI/Gemini library not installed
- API key invalid (check with provider)

### LLM Timeout

**Symptom**: "LLM request timed out"

**Fix**: Increase timeout in `app/core/config.py`:
```python
OPENAI_TIMEOUT: int = 60
```

## Resolver Issues

### All References Need Confirmation

**Symptom**: Resolver never auto-resolves

**Fix**: Lower threshold in .env:
```
RESOLVER_CONFIDENCE_THRESHOLD=0.5
```

**Debug**:
```bash
# Check resolver scoring
docker compose exec api python
>>> from app.utils.similarity import fuzzy_similarity
>>> fuzzy_similarity("meeting at 7pm", "Meeting")
```

## Performance Issues

### Slow API Responses

**Checks**:
```bash
# Check database query performance
docker compose exec db psql -U notex -d notex
# Enable query logging:
ALTER DATABASE notex SET log_statement = 'all';

# Check connection pool
# Add to API logs: structlog will show connection acquisition time
```

**Common Causes**:
- Missing database indexes (check migration)
- N+1 queries (use selectinload in repositories)
- Large message history (increase CONTEXT_MESSAGE_LIMIT)

### High Memory Usage

**Checks**:
```bash
# Check container stats
docker stats

# Check Celery worker memory
docker compose exec worker python -c "import psutil; print(f'{psutil.Process().memory_info().rss / 1024 / 1024:.2f} MB')"
```

**Fix**: Restart worker periodically or reduce batch size

## Testing Issues

### Tests Fail Locally

**Checks**:
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Check pytest configuration
pytest --version
pytest --collect-only

# Run with verbose output
pytest -vv

# Check test database
# Tests should use separate DATABASE_URL
```

## General Debugging Tips

1. **Check Logs First**: `make logs` or `docker compose logs -f`
2. **Verify Environment**: `docker compose exec api env`
3. **Test Components**: Use Python REPL to test individual modules
4. **Check Network**: `docker compose exec api ping redis`
5. **Restart Services**: `docker compose restart`
6. **Clean Start**: `docker compose down -v && docker compose up --build`

## Authentication Issues

### 401 Unauthorized on Protected Endpoints

**Symptom**: API returns 401 when accessing `/v1/*` endpoints

**Checks**:
```bash
# Verify JWT_SECRET is set
docker compose exec api python -c "from app.core.config import get_settings; print(get_settings().JWT_SECRET)"

# Test token generation
docker compose exec api python -c "
from app.auth.security import create_access_token
from uuid import uuid4
token, expires = create_access_token(uuid4())
print(f'Token: {token}')
print(f'Expires in: {expires}s')
"

# Decode a token
docker compose exec api python -c "
from app.auth.security import decode_access_token
token = 'YOUR_TOKEN_HERE'
user_id = decode_access_token(token)
print(f'User ID: {user_id}')
"
```

**Common Causes**:
- Missing `Authorization: Bearer <token>` header
- Token expired (default: 15 minutes for access tokens)
- Wrong JWT_SECRET between token creation and validation
- Clock skew between client and server

### 403 Forbidden on Resource Access

**Symptom**: Valid token but cannot access conversation/task/proposal

**Cause**: User does not own the resource

**Fix**: Ensure the conversation was created by the authenticated user

### Invalid Refresh Token

**Symptom**: "Invalid or expired refresh token" on `/auth/refresh`

**Common Causes**:
- Refresh token already used (tokens are single-use, rotate on refresh)
- Refresh token expired (default: 30 days)
- Token revoked manually
- Database was reset but client still has old tokens

**Fix**: Re-register guest user to get new tokens

### Time Synchronization Issues

**Symptom**: Tokens immediately marked as expired

**Check**:
```bash
# Check server time
docker compose exec api date -u

# Check JWT expiration
docker compose exec api python -c "
import jwt
from app.core.config import get_settings
token = 'YOUR_TOKEN_HERE'
settings = get_settings()
decoded = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], options={'verify_exp': False})
print(f'Issued at: {decoded[\"iat\"]}')
print(f'Expires at: {decoded[\"exp\"]}')
import time
print(f'Current time: {int(time.time())}')
"
```

**Fix**: Synchronize server time with NTP

### Database Migration Note

When running the `0002_guest_auth` migration on an existing database with conversations:
- If the database is **empty**: Migration runs cleanly
- If conversations **exist without users**: You must manually create users and update `user_id` references before running the migration, or drop the database and start fresh

For development, the recommended approach is:
```bash
docker compose down -v
docker compose up -d
docker compose exec api alembic upgrade head
```

## Time Confirmation Flow Issues

### Proposal Stuck in needs_confirmation

**Symptom**: Proposal remains in needs_confirmation state even after confirm-time

**Checks**:
```bash
# Check proposal status
curl -X GET http://localhost:8000/v1/proposals/{proposal_id} \
  -H "Authorization: Bearer {token}"

# Check API logs for confirm-time endpoint
docker compose logs -f api | grep confirm-time

# Verify request body format
# Must include "updates" array with proper ref structure
```

**Common Causes**:
- Wrong `ref.type` (must be "temp_id" for create ops)
- Wrong `ref.value` (must match the temp_id from the proposal)
- Proposal belongs to different user (403 error)
- Proposal not in needs_confirmation or ready state

### Clarifications Missing from Proposal

**Symptom**: needs_confirmation set but no clarifications provided

**Checks**:
```bash
# Check worker logs for time_confirmation_enforced
docker compose logs -f worker | grep time_confirmation

# Check LLM response
docker compose logs -f worker | grep llm_proposal_generated
```

**Common Causes**:
- LLM not receiving auto_apply=false context
- Worker enforcement logic not running (auto_apply=true)

### Time Suggestion Wrong Timezone

**Symptom**: Suggested times in wrong timezone

**Fix**: Pass correct timezone in message request:
```json
{
  "content": "Add meeting tomorrow",
  "auto_apply": false,
  "timezone": "Europe/Istanbul"
}
```

## List All Tasks Issues

### Tasks Not Returned

**Symptom**: GET /v1/tasks returns empty array

**Checks**:
```bash
# Verify tasks exist for user
# Check conversation-scoped tasks first
curl -X GET http://localhost:8000/v1/conversations/{id}/tasks \
  -H "Authorization: Bearer {token}"

# Check date filter range
# date_to is exclusive (tasks due on that day are excluded)
```

**Common Causes**:
- User has no tasks in any conversation
- Date range too restrictive
- Status filter excluding tasks (default is "all")
- Tasks soft-deleted (deleted_at is set)

### Wrong Tasks Returned

**Symptom**: Tasks from other users visible

**Solution**: This should never happen. If it does:
1. Check auth token is correct
2. Verify conversation.user_id is set correctly
3. Check task_repo.list_user_tasks join query

## Getting Help

If stuck:
1. Check service logs
2. Verify .env configuration
3. Test each component individually
4. Check GitHub issues
5. Enable DEBUG mode: `DEBUG=true` in .env
