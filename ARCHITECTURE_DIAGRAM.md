# Message Processing Architecture Diagram

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT REQUEST                           │
│                  POST /messages/{conversation_id}               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       API ENDPOINT                              │
│              Creates Proposal, Enqueues Task                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       CELERY QUEUE                              │
│                  process_message.delay()                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CELERY WORKER                                │
│                 tasks.process_message()                         │
│                  (Thin wrapper - 108 lines)                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  MESSAGE PROCESSOR                              │
│              (Main Orchestrator - 650 lines)                    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  PHASE 1: Validate & Prepare                           │    │
│  │  • Load context via ContextLoader                      │    │
│  │  • Publish LLM_RUNNING event                           │    │
│  │  • Update proposal to RUNNING                          │    │
│  └────────────────────────────────────────────────────────┘    │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  PHASE 2: Pre-Classified Intent Check                 │    │
│  │  • Classify message via IntentStrategyHandler          │    │
│  │  • If APPROVE/CANCEL/NOTE → Handle & Exit              │    │
│  │  • Otherwise → Continue to Phase 3                     │    │
│  └────────────────────────────────────────────────────────┘    │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  PHASE 3: Standard LLM Pipeline                        │    │
│  │  • Load messages & items context                       │    │
│  │  • Call LLM router (OPS or TOOL mode)                  │    │
│  │  • Validate payload                                    │    │
│  │  • Enrich with clarifications                          │    │
│  │  • Resolve operations                                  │    │
│  │  • Check staleness                                     │    │
│  └────────────────────────────────────────────────────────┘    │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  PHASE 4: Handle Outcome                               │    │
│  │  • If stale → STALE event & exit                       │    │
│  │  • If needs confirmation → NEEDS_CONFIRMATION event    │    │
│  │  • If no-op → READY event (tool/conversational)        │    │
│  │  • If ready + auto_apply → Apply & APPLIED event       │    │
│  │  • If ready (no auto) → READY event                    │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Service Dependencies

```
                    MessageProcessor
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
  ContextLoader    EventNotifier    ProposalStatusManager
        │                 │                 │
        │                 │                 │
        ▼                 ▼                 ▼
    Database         EventBus          Database
```

---

## Detailed Component Interaction

```
┌──────────────────────────────────────────────────────────────────────┐
│                         MessageProcessor                             │
│                                                                      │
│  process(conv_id, msg_id, version, auto_apply, tz)                 │
│    │                                                                 │
│    ├─► _validate_and_prepare()                                      │
│    │     │                                                           │
│    │     ├─► ContextLoader.load_context()                           │
│    │     │     ├─► MessageRepository.get_by_id()                    │
│    │     │     ├─► ConversationRepository.get_by_id()               │
│    │     │     ├─► ProposalRepository.list_by_conversation()        │
│    │     │     └─► UserRepository.get_by_id()                       │
│    │     │                                                           │
│    │     ├─► EventNotifier.notify_running()                         │
│    │     │     └─► EventBus.publish(WsEvent.LLM_RUNNING)            │
│    │     │                                                           │
│    │     └─► ProposalStatusManager.update_to_running()              │
│    │           └─► ProposalRepository.update_status()               │
│    │                                                                 │
│    ├─► _handle_pre_classified_intent()                              │
│    │     │                                                           │
│    │     └─► IntentStrategyHandler.handle_intent()                  │
│    │           ├─► classify_message() → IntentType?                 │
│    │           └─► dispatch_intent() → DispatchResult               │
│    │                 ├─► Update proposal status                     │
│    │                 └─► Publish appropriate event                  │
│    │                                                                 │
│    └─► _execute_standard_pipeline()                                 │
│          │                                                           │
│          ├─► ContextLoader.load_messages_context()                  │
│          ├─► ContextLoader.load_items_snapshot()                    │
│          │                                                           │
│          ├─► LlmRouterService.process_message()                     │
│          │     └─► Returns {mode, proposal, text, tool_calls}       │
│          │                                                           │
│          ├─► ProposalEnricher.enforce_time_confirmation()           │
│          │     └─► Adds DUE_AT clarifications                       │
│          │                                                           │
│          ├─► ProposalEnricher.enrich_with_upcoming_context()        │
│          │     └─► Adds nearby items to clarifications              │
│          │                                                           │
│          ├─► ProposalEnricher.detect_conflicts()                    │
│          │     └─► Adds CONFLICT clarifications                     │
│          │                                                           │
│          ├─► ResolverService.resolve_operations()                   │
│          │     └─► Resolves temp_ids to actual item IDs             │
│          │                                                           │
│          ├─► Check staleness                                        │
│          │     └─► ConversationRepository.get_version()             │
│          │                                                           │
│          └─► _handle_proposal_outcome()                             │
│                │                                                     │
│                ├─► If needs_confirmation:                           │
│                │     ├─► ProposalStatusManager.update_to_needs_conf │
│                │     └─► EventNotifier.notify_needs_confirmation()  │
│                │                                                     │
│                ├─► If no-op:                                        │
│                │     ├─► ProposalStatusManager.update_to_applied()  │
│                │     └─► EventNotifier.notify_ready(no_op=True)     │
│                │                                                     │
│                └─► If ready:                                        │
│                      ├─► ProposalStatusManager.update_to_ready()    │
│                      ├─► If auto_apply:                             │
│                      │     ├─► ProposalsService.apply_proposal()    │
│                      │     └─► EventNotifier.notify_applied()       │
│                      └─► Else:                                      │
│                            └─► EventNotifier.notify_ready()         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /messages
       ▼
┌─────────────┐
│ API Handler │ Creates Message & Proposal in DB
└──────┬──────┘
       │ Enqueues Celery task
       ▼
┌─────────────┐
│ Celery Task │ process_message()
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│ ContextLoader    │ ─────► [Database]
│  load_context()  │         - Message
└──────┬───────────┘         - Conversation
       │                     - Proposal
       │                     - User
       ▼
┌──────────────────┐
│ MessageContext   │  Immutable data container
│  (frozen)        │  - All entities
└──────┬───────────┘  - Reference time
       │              - Timezone
       │
       ▼
┌──────────────────┐
│ Intent Handler   │  Classify: APPROVE/CANCEL/NOTE?
└──────┬───────────┘
       │
       ├─► Yes: Dispatch Intent ──► Update DB ──► Publish Event ──► Return
       │
       └─► No: Continue to LLM
           │
           ▼
       ┌──────────────────┐
       │ ContextLoader    │  Load context for LLM
       │  load_messages() │   - Recent messages
       │  load_items()    │   - Active items
       └────────┬─────────┘
                │
                ▼
       ┌──────────────────┐
       │ LLM Router       │  Call OpenAI/Anthropic
       │  process()       │   - Generate ops
       └────────┬─────────┘   - Or tool response
                │
                ▼
       ┌──────────────────┐
       │ Proposal         │  Enrich with:
       │ Enricher         │   - Time clarifications
       └────────┬─────────┘   - Conflict warnings
                │             - Context items
                ▼
       ┌──────────────────┐
       │ Resolver         │  Resolve references:
       │ Service          │   - temp_id → item_id
       └────────┬─────────┘   - "last task" → item
                │
                ▼
       ┌──────────────────┐
       │ Staleness        │  Check conversation version
       │ Check            │
       └────────┬─────────┘
                │
                ├─► Stale: Update DB ──► Publish STALE ──► Return
                │
                └─► Fresh: Continue
                    │
                    ▼
               ┌──────────────────┐
               │ Outcome Handler  │
               └────────┬─────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
   Needs Conf       No-Op           Ready
        │               │               │
        ▼               ▼               ▼
   Update DB       Update DB       Update DB
        │               │               │
        ▼               ▼               ▼
  Publish Event   Publish Event    Auto-apply?
        │               │               │
        ▼               ▼           ┌───┴───┐
    Return          Return          │       │
                                    ▼       ▼
                                  Apply   Publish
                                    │     READY
                                    ▼       │
                                Publish     ▼
                                APPLIED  Return
                                    │
                                    ▼
                                 Return
```

---

## Event Flow

```
Client                API              Worker            Database         WebSocket
  │                    │                  │                 │                │
  │  POST /messages    │                  │                 │                │
  ├───────────────────>│                  │                 │                │
  │                    │  Create Proposal │                 │                │
  │                    ├─────────────────────────────────►  │                │
  │                    │                  │                 │                │
  │                    │  Enqueue Task    │                 │                │
  │                    ├─────────────────>│                 │                │
  │                    │                  │                 │                │
  │  HTTP 202 Accepted │                  │                 │                │
  │<───────────────────┤                  │                 │                │
  │                    │                  │                 │                │
  │                    │                  │  Load Context   │                │
  │                    │                  ├────────────────>│                │
  │                    │                  │                 │                │
  │                    │                  │ Publish RUNNING │                │
  │                    │                  ├─────────────────────────────────>│
  │                    │                  │                 │                │
  │                    │                  │  Call LLM       │                │
  │                    │                  │  (async)        │                │
  │                    │                  │                 │                │
  │                    │                  │  Update Proposal│                │
  │                    │                  ├────────────────>│                │
  │                    │                  │                 │                │
  │                    │                  │ Publish READY   │                │
  │                    │                  ├─────────────────────────────────>│
  │                    │                  │                 │                │
  │  WS: READY event   │                  │                 │                │
  │<─────────────────────────────────────────────────────────────────────────┤
  │                    │                  │                 │                │
  │  POST /approve     │                  │                 │                │
  ├───────────────────>│                  │                 │                │
  │                    │  Apply Proposal  │                 │                │
  │                    ├─────────────────────────────────►  │                │
  │                    │                  │                 │                │
  │                    │ Publish APPLIED  │                 │                │
  │                    ├─────────────────────────────────────────────────────>│
  │                    │                  │                 │                │
  │  WS: APPLIED event │                  │                 │                │
  │<─────────────────────────────────────────────────────────────────────────┤
```

---

## Error Handling Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    MessageProcessor.process()                │
│                                                               │
│  try:                                                         │
│    ├─► _validate_and_prepare()                              │
│    │     └─► Raises: ContextLoadError                       │
│    │                                                          │
│    ├─► _handle_pre_classified_intent()                      │
│    │     └─► Returns early or None                          │
│    │                                                          │
│    └─► _execute_standard_pipeline()                         │
│          │                                                    │
│          ├─► _call_llm_router()                             │
│          │     └─► Raises: LlmProviderConfigError           │
│          │                 LlmProviderCallError             │
│          │                 LlmProviderResponseError         │
│          │                                                    │
│          └─► ValidationError (payload validation)            │
│                                                               │
│  except ContextLoadError as e:                               │
│    ├─► Log error                                            │
│    └─► Return {"status": "error", "message": str(e)}       │
│                                                               │
│  except LlmError as e:                                       │
│    ├─► Update proposal to FAILED                            │
│    ├─► Publish PROPOSAL_FAILED event                        │
│    └─► Return {"status": "failed", "error": ...}           │
│                                                               │
│  except ValidationError as e:                                │
│    ├─► Update proposal to FAILED                            │
│    ├─► Publish PROPOSAL_FAILED event                        │
│    └─► Return {"status": "failed", "error": ...}           │
│                                                               │
│  except Exception as e:                                      │
│    ├─► Log exception with full traceback                    │
│    ├─► Try to update proposal to FAILED                     │
│    ├─► Try to publish PROPOSAL_FAILED event                 │
│    └─► Return {"status": "failed", "error": str(e)}        │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## State Machine

```
                          ┌─────────────┐
                          │   PENDING   │  (Created by API)
                          └──────┬──────┘
                                 │
                                 │ Worker starts
                                 ▼
                          ┌─────────────┐
                     ┌────│   RUNNING   │
                     │    └──────┬──────┘
                     │           │
                     │           │ Intent dispatched
                     │           ▼
                     │    ┌─────────────┐
                     │    │   APPLIED   │ (Intent: APPROVE)
                     │    └─────────────┘
                     │
                     │           │ LLM call succeeded
                     │           ▼
                     │    ┌─────────────┐
                     ├───>│    STALE    │ (Version mismatch)
                     │    └─────────────┘
                     │
                     │           │
                     │           ▼
                     │    ┌─────────────┐
                     ├───>│ NEEDS_CONF  │ (Clarifications needed)
                     │    └─────────────┘
                     │           │
                     │           │ User confirms
                     │           ▼
                     │    ┌─────────────┐
                     ├───>│    READY    │ (Ops generated, no conf needed)
                     │    └──────┬──────┘
                     │           │
                     │           │ auto_apply=true
                     │           ▼
                     │    ┌─────────────┐
                     ├───>│   APPLIED   │ (Ops applied to items)
                     │    └─────────────┘
                     │
                     │           │ Error occurred
                     │           ▼
                     │    ┌─────────────┐
                     └───>│   FAILED    │ (Error recorded)
                          └─────────────┘
```

---

## Testing Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        UNIT TESTS                            │
└──────────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  test_context_loader.py                                │
  │  • test_load_context_success()                         │
  │  • test_load_context_message_not_found()               │
  │  • test_load_messages_context()                        │
  │  • test_load_items_snapshot_with_timezone()            │
  └────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  test_event_notifier.py                                │
  │  • test_notify_running()                               │
  │  • test_notify_failed_with_error_code()                │
  │  • test_notify_stale()                                 │
  │  • test_notify_needs_confirmation()                    │
  └────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  test_intent_handler.py                                │
  │  • test_classify_approve_intent()                      │
  │  • test_handle_note_only_intent()                      │
  │  • test_handle_cancel_intent()                         │
  └────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  test_proposal_enricher.py                             │
  │  • test_enforce_time_confirmation()                    │
  │  • test_detect_conflicts()                             │
  │  • test_enrich_with_upcoming_context()                 │
  └────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     INTEGRATION TESTS                        │
└──────────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  test_message_processor.py                             │
  │  • test_full_pipeline_with_auto_apply()                │
  │  • test_pipeline_with_intent_dispatch()                │
  │  • test_pipeline_with_llm_error()                      │
  │  • test_staleness_detection()                          │
  │  • test_conflict_detection_flow()                      │
  └────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                      END-TO-END TESTS                        │
└──────────────────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────┐
  │  test_message_flow.py                                  │
  │  • test_create_message_to_applied()                    │
  │  • test_message_with_confirmation_flow()               │
  │  • test_message_with_conflict_resolution()             │
  └────────────────────────────────────────────────────────┘
```

This architecture provides **clean separation of concerns**, **easy testing**, and **maintainable code**! 🎯
