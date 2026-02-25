# Proposal Status Flow - Fixed Logic

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Message Processing Flow                          │
└─────────────────────────────────────────────────────────────────────────┘

User Message
     ↓
┌────────────────┐
│ LLM Analysis   │ → Generate ops[] and needs_confirmation flag
└────────────────┘
     ↓
┌────────────────┐
│ Task Resolver  │ → Resolve task references, set resolution.needs_confirmation
└────────────────┘
     ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     FIXED GATING LOGIC (Line 206)                       │
│                                                                          │
│  needs_confirmation = (                                                 │
│      payload.needs_confirmation OR resolution.needs_confirmation        │
│  )                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
     ↓
     ├─── needs_confirmation == TRUE ───→ [Status: NEEDS_CONFIRMATION]
     │                                     - Event: PROPOSAL_NEEDS_CONFIRMATION
     │                                     - No auto-apply (even if auto_apply=true)
     │                                     - User must confirm via API
     │                                     ✅ INVARIANT: Cannot be APPLIED
     │
     ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      NEW FIX: Check for empty ops                        │
│                                                                          │
│  if not payload.ops:  # ops == []                                       │
│      status = READY                                                     │
│      no_op = true                                                       │
│      return (skip auto-apply)                                           │
└─────────────────────────────────────────────────────────────────────────┘
     ↓
     ├─── ops == [] ───────────────────→ [Status: READY, no_op=true]
     │                                     - Event: PROPOSAL_READY {no_op: true}
     │                                     - No auto-apply (nothing to apply)
     │                                     - tasks_affected = 0
     │                                     ✅ NEW FIX: Prevents APPLIED status
     │
     ↓
     └─── ops.length > 0 ──────────────→ [Status: READY]
                                          - Event: PROPOSAL_READY
                                          - ops ready to execute
                                          ↓
                                    ┌─────────────┐
                                    │ auto_apply? │
                                    └─────────────┘
                                          ↓
                               ┌──────────┴──────────┐
                               │                     │
                           YES │                     │ NO
                               ↓                     ↓
                    ┌─────────────────────┐   Return status=ready
                    │ apply_proposal()    │   User applies manually
                    └─────────────────────┘
                               ↓
                    ┌────────────────────────────────────────┐
                    │ NEW FIX: Check ops before marking      │
                    │                                        │
                    │ if not payload.ops:                   │
                    │     return (status=READY, affected=0) │
                    └────────────────────────────────────────┘
                               ↓
                    Execute ops (create/update/delete tasks)
                               ↓
                    [Status: APPLIED]
                    - Event: PROPOSAL_APPLIED
                    - Event: TASKS_CHANGED
                    - tasks_affected > 0
                    ✅ INVARIANT: APPLIED ⟹ tasks_affected > 0


┌─────────────────────────────────────────────────────────────────────────┐
│                          Status Invariants                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. status = APPLIED  ⟹  tasks_affected > 0                            │
│     (Cannot be applied if no operations were executed)                  │
│                                                                          │
│  2. needs_confirmation = true  ⟹  status ≠ APPLIED                     │
│     (Confirmation required prevents auto-apply)                         │
│                                                                          │
│  3. ops = []  ⟹  status ∈ {READY, NEEDS_CONFIRMATION}                  │
│     (Empty ops never result in APPLIED status)                          │
│                                                                          │
│  4. resolution.needs_confirmation = true  ⟹  status ≠ APPLIED          │
│     (Resolver overrides LLM needs_confirmation flag)                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                      Bug Scenario (FIXED)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  BEFORE (Bug):                                                          │
│  ───────────                                                            │
│  Message: "maybe cancel something later"                                │
│  LLM: {ops: [], needs_confirmation: true}                              │
│  Flow: READY → auto_apply → APPLIED ❌                                 │
│  Result: status=APPLIED, tasks_affected=0  💥 BUG!                     │
│                                                                          │
│  AFTER (Fixed):                                                         │
│  ─────────────                                                          │
│  Message: "maybe cancel something later"                                │
│  LLM: {ops: [], needs_confirmation: true}                              │
│  Flow: Check needs_confirmation → NEEDS_CONFIRMATION ✅                │
│  Result: status=NEEDS_CONFIRMATION, no auto-apply ✓                    │
│                                                                          │
│  - OR -                                                                 │
│                                                                          │
│  LLM: {ops: [], needs_confirmation: false}                             │
│  Flow: Check ops.length → READY (no_op=true) ✅                        │
│  Result: status=READY, no auto-apply ✓                                 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                      Code Changes Summary                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  File: app/workers/tasks.py                                             │
│  ─────────────────────────────                                          │
│  + Added: Check for empty ops after needs_confirmation check            │
│  + Added: Early return with no_op flag                                  │
│  + Added: Skip auto-apply for empty ops                                 │
│                                                                          │
│  File: app/services/proposals_service.py                                │
│  ───────────────────────────────────────                                │
│  + Added: Validation in apply_proposal() for empty ops                  │
│  + Added: Early return with status=READY when ops=[]                    │
│  + Added: Prevent APPLIED status when tasks_affected=0                  │
│                                                                          │
│  File: tests/test_proposal_status.py (NEW)                              │
│  ───────────────────────────────────────                                │
│  + 5 comprehensive test cases                                           │
│  + Tests all status transition scenarios                                │
│  + Validates all invariants                                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```
