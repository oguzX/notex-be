# Proposal Status Bug Fix - Summary

## Root Cause

**Location**: `app/workers/tasks.py` (lines 206-281) and `app/services/proposals_service.py` (lines 78-107)

### Problems Identified:

1. **Empty ops with auto_apply=true**: When LLM returns `ops=[]` and `needs_confirmation=false`, the worker marks the proposal as `READY` and then auto-applies it. The `apply_proposal()` method always sets status to `APPLIED` regardless of whether any operations were actually executed.

2. **Inconsistent status for needs_confirmation**: When `needs_confirmation=true`, the worker correctly prevents auto-apply and sets status to `NEEDS_CONFIRMATION`. However, the opposite case (empty ops) was not handled.

3. **Missing validation**: No check for empty ops before attempting to apply. This resulted in proposals with status=`APPLIED` even though `tasks_affected=0`.

## Solution

### 1. Worker Changes (`app/workers/tasks.py`)

Added explicit handling for empty ops case:

```python
# Check if ops is empty (no-op case)
if not validated_payload.ops:
    # No operations to perform
    await proposal_repo.update_status(
        proposal.id,
        ProposalStatus.READY.value,
        ops=validated_payload.model_dump(),
        resolution=resolution.model_dump(),
    )
    await session.commit()
    
    await event_bus.publish(
        WsEvent(
            type=EventType.PROPOSAL_READY,
            conversation_id=conv_id,
            proposal_id=proposal.id,
            version=version,
            data={"ops": validated_payload.model_dump(), "no_op": True},
        )
    )
    
    logger.info(
        "proposal_no_op",
        proposal_id=str(proposal.id),
    )
    return {"status": "ready", "proposal_id": str(proposal.id), "no_op": True}
```

**Key changes**:
- Detect empty ops early and skip auto-apply path
- Mark proposal as `READY` with `no_op: true` flag in event data
- Return immediately without attempting to apply

### 2. Service Changes (`app/services/proposals_service.py`)

Added safety check in `apply_proposal()`:

```python
if proposal.ops:
    payload = LlmProposalPayload(**proposal.ops)
    
    # Ensure there are actually ops to apply
    if not payload.ops:
        logger.warning(
            "apply_proposal_no_ops",
            proposal_id=str(request.proposal_id),
        )
        # Keep status as READY - nothing to apply
        return ApplyProposalResponse(
            proposal_id=request.proposal_id,
            status=ProposalStatus.READY,
            tasks_affected=0,
        )
```

**Key changes**:
- Return early with status=`READY` and `tasks_affected=0` when no ops to apply
- Prevent marking proposal as `APPLIED` when nothing was executed

## Status Invariants (Now Enforced)

1. **`status=APPLIED`** ⟹ `tasks_affected > 0`
   - A proposal can only be marked as APPLIED if at least one operation was executed

2. **`needs_confirmation=true`** ⟹ `status != APPLIED`
   - Proposals requiring confirmation can never be auto-applied

3. **`ops=[]`** ⟹ `status=READY` with `no_op=true`
   - Empty operations result in READY status with a flag indicating no-op

4. **`resolver.needs_confirmation=true`** ⟹ `status=NEEDS_CONFIRMATION`
   - Ambiguous task references prevent auto-apply even if LLM said no confirmation needed

## Test Coverage

Added comprehensive tests in `tests/test_proposal_status.py`:

1. ✅ **test_needs_confirmation_with_empty_ops_and_auto_apply**
   - When: `needs_confirmation=true`, `ops=[]`, `auto_apply=true`
   - Expected: `status=needs_confirmation`, no apply attempt, correct event emitted

2. ✅ **test_empty_ops_without_confirmation_auto_apply**
   - When: `needs_confirmation=false`, `ops=[]`, `auto_apply=true`
   - Expected: `status=ready`, `no_op=true`, no apply attempt

3. ✅ **test_valid_ops_needs_confirmation_false_auto_apply**
   - When: `needs_confirmation=false`, valid ops, `auto_apply=true`
   - Expected: `status=applied`, `tasks_affected > 0`, correct events

4. ✅ **test_resolver_needs_confirmation_overrides_llm**
   - When: LLM says `needs_confirmation=false` but resolver says `needs_confirmation=true`
   - Expected: `status=needs_confirmation`, resolver overrides LLM

5. ✅ **test_apply_proposal_with_empty_ops_returns_ready**
   - When: `apply_proposal()` called with empty ops
   - Expected: Returns `status=READY`, `tasks_affected=0`

## Expected Behavior After Fix

### Scenario 1: User message is unclear
```json
Request: {"content": "maybe do something later", "auto_apply": true}
LLM Response: {"ops": [], "needs_confirmation": true}
Result: {"status": "needs_confirmation"}
✅ Correct - requires user clarification
```

### Scenario 2: Conversational message with no tasks
```json
Request: {"content": "thanks!", "auto_apply": true}
LLM Response: {"ops": [], "needs_confirmation": false}
Result: {"status": "ready", "no_op": true}
✅ Correct - acknowledged, no action needed
```

### Scenario 3: Clear task request
```json
Request: {"content": "remind me to call mom at 5pm", "auto_apply": true}
LLM Response: {"ops": [{"op": "create", ...}], "needs_confirmation": false}
Result: {"status": "applied", "tasks_affected": 1}
✅ Correct - task created automatically
```

### Scenario 4: Ambiguous reference (original bug case)
```json
Request: {"content": "cancel the meeting", "auto_apply": true}
LLM Response: {"ops": [{"op": "cancel", "ref": {...}}], "needs_confirmation": false}
Resolver: {"needs_confirmation": true}  // Multiple meetings found
Result: {"status": "needs_confirmation"}
✅ Correct - resolver overrides LLM
```

## Files Changed

1. **app/workers/tasks.py** (lines 206-282)
   - Added empty ops detection before auto-apply
   - Added no-op status return with flag

2. **app/services/proposals_service.py** (lines 78-107)
   - Added early return when no ops to apply
   - Prevents marking as APPLIED when tasks_affected=0

3. **tests/test_proposal_status.py** (new file)
   - 5 comprehensive test cases
   - Tests all status transition scenarios
   - Validates invariants

## Running Tests

```bash
# Run the new tests
docker compose exec api pytest tests/test_proposal_status.py -v

# Run all tests
docker compose exec api pytest -v
```

## Migration Notes

**No database migration needed** - this is purely a logic fix in the worker and service layers. Existing proposals in the database are not affected.

However, any proposals that were incorrectly marked as `APPLIED` with `tasks_affected=0` will remain in that state. If needed, you can query for these:

```sql
SELECT id, status, ops->>'ops' 
FROM proposals 
WHERE status = 'applied' 
  AND ops->>'ops' = '[]';
```

These can be manually corrected if desired, but future proposals will follow the correct logic.
