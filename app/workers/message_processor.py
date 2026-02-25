"""Message processor orchestrator."""

from typing import Any
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.item_repo import ItemRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.llm.errors import (
    LlmProviderCallError,
    LlmProviderConfigError,
    LlmProviderResponseError,
)
from app.llm.intent_router import IntentRouterAgent
from app.schemas.events import MessageOpsPayload
from app.schemas.intents import RouterDecisionType
from app.schemas.proposals import (
    ApplyProposalRequest,
    LlmProposalPayload,
)
from app.services.proposals_service import ProposalsService
from app.services.resolver_service import ResolverService
from app.workers.context_loader import ContextLoadError, ContextLoader
from app.workers.event_notifier import EventNotifier
from app.workers.intent_handler import IntentStrategyHandler
from app.workers.message_context import MessageContext
from app.workers.proposal_enricher import ProposalEnricher
from app.workers.proposal_manager import ProposalStatusManager

logger = structlog.get_logger(__name__)


class MessageProcessor:
    """
    Main orchestrator for message processing.

    Coordinates the workflow:
    1. Load Context
    2. Check Pre-classified Intent (early exit)
    3. Execute Standard Pipeline (LLM processing)
    4. Handle Proposal Outcome (status-based routing)

    Delegates to specialized services for each concern.
    """

    def __init__(self, session: AsyncSession, event_notifier: EventNotifier):
        """
        Initialize MessageProcessor.

        Args:
            session: Database session
            event_notifier: Event notifier service
        """
        self.session = session
        self.event_notifier = event_notifier

        # Initialize services
        self.context_loader = ContextLoader(session)
        self.intent_handler = IntentStrategyHandler(session, event_notifier)
        self.proposal_manager = ProposalStatusManager(session)
        self.item_repo = ItemRepository(session)
        self.proposal_enricher = ProposalEnricher(self.item_repo)
        self.conversation_repo = ConversationRepository(session)
        self.proposal_repo = ProposalRepository(session)

        # Initialize Intent Router Agent
        try:
            self.intent_router = IntentRouterAgent()
        except LlmProviderConfigError as e:
            logger.warning("intent_router_disabled", error=str(e))
            self.intent_router = None

    async def process(
        self,
        conversation_id: UUID,
        message_id: UUID,
        version: int,
        auto_apply: bool,
        timezone: str,
    ) -> dict[str, Any]:
        """
        Main entry point for message processing.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            version: Conversation version
            auto_apply: Whether to auto-apply proposals
            timezone: User timezone

        Returns:
            Processing result dictionary
        """
        logger.info(
            "processing_message",
            conversation_id=str(conversation_id),
            message_id=str(message_id),
            version=version,
            auto_apply=auto_apply,
        )

        try:
            # Step 1: Validate and prepare
            context = await self._validate_and_prepare(
                conversation_id,
                message_id,
                version,
                auto_apply,
                timezone,
            )

            # Step 2: Route message using Intent Router Agent
            router_result, resolved_mode = await self._route_message_with_agent(context)
            if router_result is not None:
                return router_result

            # Step 3: Execute standard pipeline (LLM processing)
            return await self._execute_standard_pipeline(context, resolved_mode=resolved_mode)

        except ContextLoadError as e:
            logger.error("context_load_error", error=str(e), field=e.field)
            return {"status": "error", "message": str(e)}

        except Exception as e:
            logger.exception(
                "message_processing_error",
                conversation_id=str(conversation_id),
                message_id=str(message_id),
                error=str(e),
            )

            # Try to update proposal status if we have the context
            try:
                # We may not have context if error occurred during loading
                # Load proposal separately for error handling
                from app.db.repositories.proposal_repo import ProposalRepository

                proposal_repo = ProposalRepository(self.session)
                proposals = await proposal_repo.list_by_conversation(
                    conversation_id,
                    limit=100,
                )
                proposal = None
                for p in proposals:
                    if p.message_id == message_id and p.version == version:
                        proposal = p
                        break

                if proposal:
                    await self.proposal_manager.update_to_failed(
                        proposal.id,
                        str(e),
                    )

                    await self.event_notifier.notify_failed(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        proposal_id=proposal.id,
                        version=version,
                        error=str(e),
                    )
            except Exception as cleanup_error:
                logger.error("error_cleanup_failed", error=str(cleanup_error))

            return {"status": "failed", "error": str(e)}

    async def _validate_and_prepare(
        self,
        conversation_id: UUID,
        message_id: UUID,
        version: int,
        auto_apply: bool,
        timezone: str,
    ) -> MessageContext:
        """
        Load and validate context, publish running event.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            version: Conversation version
            auto_apply: Whether to auto-apply
            timezone: User timezone

        Returns:
            MessageContext with all loaded data

        Raises:
            ContextLoadError: If context cannot be loaded
        """
        # Load context
        context = await self.context_loader.load_context(
            conversation_id,
            message_id,
            version,
            auto_apply,
            timezone,
        )

        # Publish running event
        await self.event_notifier.notify_running(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
        )

        # Update proposal to running
        await self.proposal_manager.update_to_running(context.proposal.id)

        return context

    async def _route_message_with_agent(
        self,
        context: MessageContext,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Route message using Intent Router Agent.

        Returns:
            Tuple of (result, resolved_mode):
            - (result_dict, None) if intent was fully handled (confirm/reject)
            - (None, "ops"/"tool") to continue pipeline with pre-resolved mode
            - (None, None) fallback to full pipeline with classify_intent
        """
        # If router is disabled (config error), fall back to old system
        if not self.intent_router:
            logger.warning("router_disabled_using_fallback")
            legacy_result = await self._handle_pre_classified_intent_legacy(context)
            return (legacy_result, None)

        try:
            # Step 1: Get active proposal context
            active_proposal = await self._get_active_proposal_context(
                context.conversation_id
            )

            # Step 2: Route the message
            decision = await self.intent_router.route(
                user_message=context.message.content,
                active_proposal=active_proposal,
            )

            logger.info(
                "router_decision",
                decision=decision.decision.value,
                confidence=decision.confidence,
                has_active_proposal=active_proposal is not None,
            )

            # Step 3: Handle decision
            if decision.decision == RouterDecisionType.CONFIRM_PROPOSAL:
                result = await self._handle_confirm_proposal(context, active_proposal)
                return (result, None)

            elif decision.decision == RouterDecisionType.REJECT_PROPOSAL:
                result = await self._handle_reject_proposal(context, active_proposal)
                return (result, None)

            elif decision.decision == RouterDecisionType.MODIFY_PROPOSAL:
                logger.info(
                    "modify_proposal_detected",
                    modification=decision.suggested_modification,
                )
                return (None, "ops")

            elif decision.decision == RouterDecisionType.TOOL_QUERY:
                logger.info("tool_query_detected")
                return (None, "tool")

            elif decision.decision == RouterDecisionType.CREATE_TASK_OR_NOTE:
                logger.info("create_task_or_note_detected")
                return (None, "ops")

            # Should never reach here, fail-safe
            return (None, None)

        except Exception as e:
            logger.error(
                "router_agent_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fail-safe: continue to standard pipeline
            return (None, None)

    async def _get_active_proposal_context(
        self,
        conversation_id: UUID,
    ) -> dict[str, Any] | None:
        """
        Get active proposal context for routing decisions.

        Returns:
            Proposal dict if there's an active proposal with status='needs_confirmation',
            None otherwise
        """
        try:
            # Get latest actionable proposal (ready or needs_confirmation)
            proposal = await self.proposal_repo.get_latest_actionable(conversation_id)

            if not proposal:
                return None

            # Only consider proposals that need confirmation
            if proposal.status != "needs_confirmation":
                return None

            # Return proposal data as dict
            return {
                "id": proposal.id,
                "status": proposal.status,
                "ops": proposal.ops,
                "resolution": proposal.resolution,
                "message_id": proposal.message_id,
                "version": proposal.version,
            }

        except Exception as e:
            logger.error("get_active_proposal_error", error=str(e))
            return None

    async def _handle_confirm_proposal(
        self,
        context: MessageContext,
        active_proposal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle CONFIRM_PROPOSAL decision."""
        if not active_proposal:
            logger.warning("confirm_without_active_proposal")
            # Fallback to standard pipeline
            return None

        logger.info(
            "confirming_proposal",
            proposal_id=str(active_proposal["id"]),
        )

        # Apply the proposal
        proposals_service = ProposalsService(self.session)
        result = await proposals_service.apply_proposal(
            ApplyProposalRequest(proposal_id=active_proposal["id"])
        )

        # Update current proposal to applied
        await self.proposal_manager.update_to_applied(
            context.proposal.id,
            LlmProposalPayload(ops=[], needs_confirmation=False, reasoning="Confirmation acknowledged"),
            resolution=None,
        )

        # Build message ops for the APPLIED proposal
        from app.schemas.events import MessageOpsPayload
        message_ops = MessageOpsPayload(
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            ops=[],
            resolution=None,
            clarifications=[],
            no_op=True,
            tool_response=None,
        )

        await self.event_notifier.notify_applied(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            items_affected=result.items_affected,
        )

        return {
            "status": "applied",
            "proposal_id": str(active_proposal["id"]),
            "items_affected": result.items_affected,
            "router_decision": "confirm_proposal",
        }

    async def _handle_reject_proposal(
        self,
        context: MessageContext,
        active_proposal: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle REJECT_PROPOSAL decision."""
        if not active_proposal:
            logger.warning("reject_without_active_proposal")
            # Fallback to standard pipeline
            return None

        logger.info(
            "rejecting_proposal",
            proposal_id=str(active_proposal["id"]),
        )

        # Cancel the active proposal
        await self.proposal_repo.update_status(
            active_proposal["id"],
            status="canceled",
        )

        # Update current proposal to canceled
        await self.proposal_manager.update_to_canceled(context.proposal.id)

        await self.session.commit()

        # Build message ops
        from app.schemas.events import MessageOpsPayload
        message_ops = MessageOpsPayload(
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            ops=[],
            resolution=None,
            clarifications=[],
            no_op=True,
            tool_response=None,
        )

        await self.event_notifier.notify_applied(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            items_affected=0,
            intent="cancel_proposal",
        )

        return {
            "status": "canceled",
            "proposal_id": str(active_proposal["id"]),
            "items_affected": 0,
            "router_decision": "reject_proposal",
        }

    async def _handle_pre_classified_intent_legacy(
        self,
        context: MessageContext,
    ) -> dict[str, Any] | None:
        """
        Legacy fallback for pre-classified intents (old regex-based system).

        This is kept as a fallback when the Intent Router Agent is disabled.

        Args:
            context: Message context

        Returns:
            Result dict if intent was handled, None to continue pipeline
        """
        intent = self.intent_handler.classify_message(context.message.content)

        if not intent:
            return None

        logger.info("pre_classified_intent_detected", intent=intent.value)

        result = await self.intent_handler.handle_intent(intent, context)

        if not result.handled:
            return None

        return {
            "status": result.status,
            "intent": intent.value,
            "proposal_id": str(result.proposal_id) if result.proposal_id else None,
            "items_affected": result.items_affected,
        }

    async def _execute_standard_pipeline(
        self,
        context: MessageContext,
        resolved_mode: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute standard LLM processing pipeline.

        Args:
            context: Message context

        Returns:
            Processing result dictionary
        """
        # Load messages and items context
        messages_context = await self.context_loader.load_messages_context(
            context.conversation_id
        )
        items_snapshot = await self.context_loader.load_items_snapshot(
            context.conversation_id,
            timezone=context.user_timezone,
        )

        # Call LLM router
        try:
            llm_result = await self._call_llm_router(
                messages_context,
                items_snapshot,
                context,
                resolved_mode=resolved_mode,
            )
        except (LlmProviderConfigError, LlmProviderCallError, LlmProviderResponseError) as e:
            return await self._handle_llm_error(e, context)

        # Extract mode and payload
        mode = llm_result.get("mode")
        tool_response_data = None

        if mode == "tool":
            llm_payload = LlmProposalPayload(
                ops=[],
                needs_confirmation=False,
                reasoning=llm_result.get("text", "Tool response"),
            )
            tool_response_data = {
                "text": llm_result.get("text"),
                "tool_calls": llm_result.get("tool_calls", []),
            }
        else:
            llm_payload = llm_result.get("proposal")

        # Validate payload
        try:
            validated_payload = LlmProposalPayload(**llm_payload.model_dump(mode="json"))
        except ValidationError as e:
            return await self._handle_validation_error(e, context)

        logger.info(
            "llm_proposal_generated",
            ops_count=len(validated_payload.ops),
            needs_confirmation=validated_payload.needs_confirmation,
        )

        # Enrich payload
        validated_payload = await self._enrich_payload(validated_payload, context)

        # Resolve operations
        resolver = ResolverService(self.session)
        resolution = await resolver.resolve_operations(
            context.conversation_id,
            validated_payload.ops,
            context.user_timezone,
            reference_dt_utc=context.reference_dt_utc,
        )

        # Check for staleness
        if await self._is_stale(context):
            return await self._handle_stale_proposal(
                validated_payload,
                resolution,
                context,
                tool_response_data,
            )

        # Determine if confirmation needed
        needs_confirmation = (
            validated_payload.needs_confirmation or resolution.needs_confirmation
        )

        # Handle based on outcome
        return await self._handle_proposal_outcome(
            validated_payload,
            resolution,
            context,
            needs_confirmation,
            tool_response_data,
        )

    async def _call_llm_router(
        self,
        messages_context: list[dict[str, str]],
        items_snapshot: list[dict[str, Any]],
        context: MessageContext,
        resolved_mode: str | None = None,
    ) -> dict[str, Any]:
        """Call LLM router service.

        If resolved_mode is provided, skips intent classification
        and routes directly to the appropriate LLM mode.
        """
        from app.llm.router import LlmRouterService

        router = LlmRouterService()

        if resolved_mode == "tool":
            return await router.process_tool_mode(messages_context)

        if resolved_mode == "ops":
            return await router.process_ops_mode(
                messages_context,
                items_snapshot,
                context.user_timezone,
                context.auto_apply,
                context.reference_dt_utc,
            )

        # Fallback: no pre-resolved mode, use full classify_intent
        return await router.process_message(
            messages_context,
            items_snapshot,
            context.user_timezone,
            auto_apply=context.auto_apply,
            reference_dt_utc=context.reference_dt_utc,
        )

    async def _handle_llm_error(
        self,
        error: Exception,
        context: MessageContext,
    ) -> dict[str, Any]:
        """Handle LLM provider errors."""
        error_code = getattr(error, "error_code", None)
        error_message = getattr(error, "message", str(error))
        error_details = getattr(error, "details", {})

        logger.error(
            "llm_error",
            error_type=type(error).__name__,
            error=error_message,
            error_code=error_code,
        )

        await self.proposal_manager.update_to_failed(
            context.proposal.id,
            error_message,
            error_details={"error_code": error_code, "details": error_details},
        )

        await self.event_notifier.notify_failed(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            error=error_message,
            error_code=error_code,
        )

        return {
            "status": "failed",
            "error_code": error_code,
            "error": error_message,
        }

    async def _handle_validation_error(
        self,
        error: ValidationError,
        context: MessageContext,
    ) -> dict[str, Any]:
        """Handle payload validation errors."""
        logger.error("llm_payload_validation_error", error=str(error))

        await self.proposal_manager.update_to_failed(
            context.proposal.id,
            "Invalid LLM response",
            error_details={"validation_error": str(error)},
        )

        await self.event_notifier.notify_failed(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            error="Invalid LLM response",
        )

        return {"status": "failed", "error": "Invalid LLM response"}

    async def _enrich_payload(
        self,
        payload: LlmProposalPayload,
        context: MessageContext,
    ) -> LlmProposalPayload:
        """Enrich payload with clarifications and context."""
        # Enforce time confirmation if auto_apply=false
        if not context.auto_apply:
            payload = self.proposal_enricher.enforce_time_confirmation(
                payload,
                context.user_timezone,
            )
            # Enrich clarifications with upcoming items context
            payload = await self.proposal_enricher.enrich_with_upcoming_context(
                payload,
                context.conversation.user_id,
                context.user_timezone,
            )

        # Detect scheduling conflicts
        payload = await self.proposal_enricher.detect_and_add_conflict_clarifications(
            payload,
            context.conversation.user_id,
            context.user_timezone,
        )

        return payload

    async def _is_stale(self, context: MessageContext) -> bool:
        """Check if proposal is stale."""
        current_version = await self.conversation_repo.get_version(
            context.conversation_id
        )
        return current_version != context.version

    async def _handle_stale_proposal(
        self,
        payload: LlmProposalPayload,
        resolution: Any,
        context: MessageContext,
        tool_response_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle stale proposal."""
        logger.warning(
            "proposal_stale",
            proposal_id=str(context.proposal.id),
        )

        await self.proposal_manager.update_to_stale(
            context.proposal.id,
            payload,
            resolution,
        )

        message_ops = self._build_message_ops_payload(
            payload,
            resolution,
            context,
            tool_response_data,
        )

        await self.event_notifier.notify_stale(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
        )

        return {"status": "stale"}

    async def _handle_proposal_outcome(
        self,
        payload: LlmProposalPayload,
        resolution: Any,
        context: MessageContext,
        needs_confirmation: bool,
        tool_response_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Route to appropriate handler based on proposal outcome."""
        if needs_confirmation:
            return await self._handle_needs_confirmation(
                payload,
                resolution,
                context,
                tool_response_data,
            )

        if not payload.ops:
            return await self._handle_no_op(
                payload,
                resolution,
                context,
                tool_response_data,
            )

        return await self._handle_ready_proposal(
            payload,
            resolution,
            context,
            tool_response_data,
        )

    async def _handle_needs_confirmation(
        self,
        payload: LlmProposalPayload,
        resolution: Any,
        context: MessageContext,
        tool_response_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle proposal that needs confirmation."""
        await self.proposal_manager.update_to_needs_confirmation(
            context.proposal.id,
            payload,
            resolution,
        )

        message_ops = self._build_message_ops_payload(
            payload,
            resolution,
            context,
            tool_response_data,
        )

        await self.event_notifier.notify_needs_confirmation(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            resolution=resolution.model_dump(mode="json"),
            clarifications=[c.model_dump(mode="json") for c in payload.clarifications],
        )

        logger.info("proposal_needs_confirmation", proposal_id=str(context.proposal.id))
        return {"status": "needs_confirmation", "proposal_id": str(context.proposal.id)}

    async def _handle_no_op(
        self,
        payload: LlmProposalPayload,
        resolution: Any,
        context: MessageContext,
        tool_response_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle no-op proposal (tool mode or conversational)."""
        await self.proposal_manager.update_to_applied(
            context.proposal.id,
            payload,
            resolution,
        )

        message_ops = self._build_message_ops_payload(
            payload,
            resolution,
            context,
            tool_response_data,
        )

        await self.event_notifier.notify_ready(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            no_op=True,
            tool_response=tool_response_data,
        )

        logger.info(
            "proposal_no_op",
            proposal_id=str(context.proposal.id),
            is_tool_mode=tool_response_data is not None,
        )

        result_data = {
            "status": "ready",
            "proposal_id": str(context.proposal.id),
            "no_op": True,
        }
        if tool_response_data:
            result_data["tool_response"] = tool_response_data
        return result_data

    async def _handle_ready_proposal(
        self,
        payload: LlmProposalPayload,
        resolution: Any,
        context: MessageContext,
        tool_response_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle ready proposal (with or without auto-apply)."""
        await self.proposal_manager.update_to_ready(
            context.proposal.id,
            payload,
            resolution,
        )

        message_ops = self._build_message_ops_payload(
            payload,
            resolution,
            context,
            tool_response_data,
        )

        if context.auto_apply:
            return await self._auto_apply_proposal(
                payload,
                context,
                message_ops,
            )

        # Ready but not auto-applying
        op_titles = [op.title for op in payload.ops if op.title]

        await self.event_notifier.notify_ready(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            titles=op_titles,
            reasoning=payload.reasoning,
        )

        return {"status": "ready", "proposal_id": str(context.proposal.id)}

    async def _auto_apply_proposal(
        self,
        payload: LlmProposalPayload,
        context: MessageContext,
        message_ops: MessageOpsPayload,
    ) -> dict[str, Any]:
        """Auto-apply a ready proposal."""
        logger.info("auto_applying_proposal", proposal_id=str(context.proposal.id))

        proposals_service = ProposalsService(self.session)
        result = await proposals_service.apply_proposal(
            ApplyProposalRequest(proposal_id=context.proposal.id)
        )

        await self.event_notifier.notify_applied(
            conversation_id=context.conversation_id,
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            message_ops=message_ops,
            items_affected=result.items_affected,
        )

        return {
            "status": "applied",
            "proposal_id": str(context.proposal.id),
            "items_affected": result.items_affected,
        }

    def _build_message_ops_payload(
        self,
        payload: LlmProposalPayload,
        resolution: Any,
        context: MessageContext,
        tool_response_data: dict[str, Any] | None,
    ) -> MessageOpsPayload:
        """Build message ops payload for WebSocket events."""
        ops_list = [op.model_dump(mode="json") for op in payload.ops]
        clarifications_list = [c.model_dump(mode="json") for c in payload.clarifications]
        resolution_dict = resolution.model_dump(mode="json") if resolution else None

        no_op = len(ops_list) == 0

        return MessageOpsPayload(
            message_id=context.message_id,
            proposal_id=context.proposal.id,
            version=context.version,
            ops=ops_list,
            resolution=resolution_dict,
            clarifications=clarifications_list,
            no_op=no_op,
            tool_response=tool_response_data,
        )
