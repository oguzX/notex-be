"""Proposals service."""

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ClarificationNotFoundError,
    NoApprovableProposalError,
    ProposalAlreadyProcessedError,
    ProposalNotFoundError,
    ProposalNotReadyError,
    StaleProposalError,
)
from app.db.repositories.conversation_repo import ConversationRepository
from app.db.repositories.item_event_repo import ItemEventRepository
from app.db.repositories.item_repo import ItemRepository
from app.db.repositories.proposal_repo import ProposalRepository
from app.events.bus import get_event_bus
from app.schemas.enums import (
    ClarificationField,
    ConfirmAction,
    EventType,
    ItemRefType,
    ItemStatus,
    ItemType,
    OpType,
    ProposalStatus,
)
from app.schemas.events import WsEvent
from app.schemas.proposals import (
    ApplyProposalRequest,
    ApplyProposalResponse,
    Clarification,
    ClarificationContext,
    ConfirmRequest,
    ConfirmResponse,
    ConfirmUpdate,
    ConflictInfo,
    ItemOp,
    ItemRef,
    LlmProposalPayload,
    ProposalResponse,
    TimeSuggestion,
    UpcomingItemSummary,
)
from app.utils.ids import generate_clarification_id
from app.utils.time import ensure_utc, parse_natural_time

logger = structlog.get_logger(__name__)


class ProposalsService:
    """Service for proposal operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.proposal_repo = ProposalRepository(session)
        self.item_repo = ItemRepository(session)
        self.item_event_repo = ItemEventRepository(session)
        self.conversation_repo = ConversationRepository(session)

    async def get_proposal(self, proposal_id: UUID) -> ProposalResponse | None:
        """Get a proposal by ID."""
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if not proposal:
            return None
        return ProposalResponse.model_validate(proposal)

    async def list_proposals(self, conversation_id: UUID) -> list[ProposalResponse]:
        """List proposals for a conversation."""
        proposals = await self.proposal_repo.list_by_conversation(conversation_id)
        return [ProposalResponse.model_validate(p) for p in proposals]

    async def approve_proposal(
        self,
        conversation_id: UUID,
        proposal_id: UUID | None = None,
    ) -> ApplyProposalResponse:
        """Approve and apply a proposal without creating a new message/proposal.

        If *proposal_id* is given, that specific proposal is used.
        Otherwise the latest actionable (ready / needs_confirmation) proposal
        for the conversation is resolved automatically.

        Raises domain errors when no valid proposal can be found or it is in an
        invalid state.
        """
        if proposal_id:
            proposal = await self.proposal_repo.get_by_id(proposal_id)
            if not proposal:
                raise ProposalNotFoundError(str(proposal_id))
            # Ensure proposal belongs to the conversation
            if proposal.conversation_id != conversation_id:
                raise ProposalNotFoundError(str(proposal_id))
        else:
            proposal = await self.proposal_repo.get_latest_actionable(conversation_id)
            if not proposal:
                raise NoApprovableProposalError(str(conversation_id))

        # Delegate to apply_proposal which handles status / staleness checks
        return await self.apply_proposal(
            ApplyProposalRequest(proposal_id=proposal.id),
        )

    async def apply_proposal(
        self,
        request: ApplyProposalRequest,
    ) -> ApplyProposalResponse:
        """
        Apply a proposal, creating/updating/deleting items.
        
        This is called either automatically by the worker (if auto_apply=true)
        or manually via the API endpoint.
        """
        proposal = await self.proposal_repo.get_by_id(request.proposal_id)
        if not proposal:
            raise ProposalNotFoundError(str(request.proposal_id))
        
        # Check if already processed (idempotency)
        if proposal.status in [
            ProposalStatus.APPLIED.value,
            ProposalStatus.CANCELED.value,
        ]:
            raise ProposalAlreadyProcessedError(
                str(request.proposal_id), proposal.status
            )
        
        # Check if proposal is ready
        if proposal.status not in [
            ProposalStatus.READY.value,
            ProposalStatus.NEEDS_CONFIRMATION.value,
        ]:
            raise ProposalNotReadyError(str(request.proposal_id), proposal.status)
        
        # Check if stale
        current_version = await self.conversation_repo.get_version(
            proposal.conversation_id
        )
        # if current_version != proposal.version:
        #     raise StaleProposalError(
        #         str(request.proposal_id),
        #         current_version or 0,
        #         proposal.version,
        #     )
        
        # Apply operations
        items_affected = 0
        
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
                    items_affected=0,
                )
            
            # Resolve user timezone for correct time interpretation
            user_tz = "UTC"
            conversation = await self.conversation_repo.get_by_id(
                proposal.conversation_id
            )
            if conversation:
                from app.db.repositories.user_repo import UserRepository
                user_repo = UserRepository(self.session)
                user = await user_repo.get_by_id(conversation.user_id)
                if user and user.timezone:
                    user_tz = user.timezone

            for op_data in payload.ops:
                await self._apply_op(
                    proposal.conversation_id,
                    proposal.id,
                    op_data,
                    request.confirmed_resolutions,
                    timezone=user_tz,
                    force_item_type=request.force_item_type,
                )
                items_affected += 1
        
        # Update proposal status to APPLIED only if ops were executed
        await self.proposal_repo.update_status(
            request.proposal_id,
            ProposalStatus.APPLIED.value,
        )
        
        await self.session.commit()
        
        logger.info(
            "proposal_applied",
            proposal_id=str(request.proposal_id),
            items_affected=items_affected,
        )
        
        # Publish events
        event_bus = get_event_bus()
        await event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_APPLIED,
                conversation_id=proposal.conversation_id,
                proposal_id=proposal.id,
                version=proposal.version,
                data={"items_affected": items_affected},
            )
        )
        await event_bus.publish(
            WsEvent(
                type=EventType.ITEMS_CHANGED,
                conversation_id=proposal.conversation_id,
                version=proposal.version,
            )
        )
        
        return ApplyProposalResponse(
            proposal_id=request.proposal_id,
            status=ProposalStatus.APPLIED,
            items_affected=items_affected,
        )

    async def _apply_op(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
        timezone: str = "UTC",
        force_item_type: str | None = None,
    ) -> None:
        """Apply a single operation."""
        if op.op == OpType.CREATE:
            await self._apply_create(conversation_id, proposal_id, op, timezone=timezone, force_item_type=force_item_type)
        elif op.op == OpType.UPDATE:
            await self._apply_update(conversation_id, proposal_id, op, confirmed_resolutions, timezone=timezone)
        elif op.op in [OpType.DELETE, OpType.CANCEL]:
            await self._apply_delete(conversation_id, proposal_id, op, confirmed_resolutions)
        elif op.op == OpType.DONE:
            await self._apply_done(conversation_id, proposal_id, op, confirmed_resolutions)
        elif op.op == OpType.ARCHIVE:
            await self._apply_archive(conversation_id, proposal_id, op, confirmed_resolutions)
        elif op.op == OpType.UNARCHIVE:
            await self._apply_unarchive(conversation_id, proposal_id, op, confirmed_resolutions)
        elif op.op == OpType.PIN:
            await self._apply_pin(conversation_id, proposal_id, op, confirmed_resolutions)
        elif op.op == OpType.UNPIN:
            await self._apply_unpin(conversation_id, proposal_id, op, confirmed_resolutions)

    async def _apply_create(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        timezone: str = "UTC",
        force_item_type: str | None = None,
    ) -> None:
        """Apply create operation."""
        # Get conversation to get user_id
        conversation = await self.conversation_repo.get_by_id(conversation_id)
        if not conversation:
            logger.warning("conversation_not_found_for_create", conversation_id=str(conversation_id))
            return
        
        # Parse due_at if provided — always interpret in user timezone, store as UTC
        due_at = None
        if op.due_at:
            due_at = parse_natural_time(op.due_at, tz=timezone)
            if due_at:
                due_at = ensure_utc(due_at)
        
        # Determine item type (allow override via force_item_type)
        if force_item_type:
            item_type = force_item_type if isinstance(force_item_type, str) else force_item_type.value
        else:
            item_type = op.item_type.value if op.item_type else "TASK"
        
        # Always store the user timezone on the item for correct display later
        item_timezone = op.suggested_timezone or timezone

        item = await self.item_repo.create(
            conversation_id=conversation_id,
            user_id=conversation.user_id,
            item_type=item_type,
            title=op.title or "Untitled Item",
            content=op.content,
            due_at=due_at,
            timezone=item_timezone,
            priority=op.priority or "MEDIUM",
            category=op.category or "GENERAL",
            status="ACTIVE",
            pinned=op.pinned if op.pinned else False,
            tags=op.tags if op.tags else [],
        )
        
        # Create event
        await self.item_event_repo.create(
            item_id=item.id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="CREATED",
            after={"title": item.title, "status": item.status, "type": item.type},
        )

    async def _apply_update(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
        timezone: str = "UTC",
    ) -> None:
        """Apply update operation."""
        if not op.ref:
            return
        
        # Resolve item ID
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_update", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        # Build update fields
        updates = {}
        if op.title:
            updates["title"] = op.title
        if op.content is not None:
            updates["content"] = op.content
        if op.due_at:
            parsed_due = parse_natural_time(op.due_at, tz=timezone)
            updates["due_at"] = ensure_utc(parsed_due) if parsed_due else None
        if op.priority:
            updates["priority"] = op.priority
        if op.category is not None:
            updates["category"] = op.category
        if op.pinned is not None:
            updates["pinned"] = op.pinned
        if op.tags is not None:
            updates["tags"] = op.tags
        
        if updates:
            before = {"title": item.title, "status": item.status, "type": item.type}
            await self.item_repo.update(item_id, **updates)
            updated_item = await self.item_repo.get_by_id(item_id)
            after = {"title": updated_item.title, "status": updated_item.status, "type": updated_item.type} if updated_item else {}
            
            await self.item_event_repo.create(
                item_id=item_id,
                conversation_id=conversation_id,
                proposal_id=proposal_id,
                event_type="UPDATED",
                before=before,
                after=after,
            )

    async def _apply_delete(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> None:
        """Apply delete/cancel operation."""
        if not op.ref:
            return
        
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_delete", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        before = {"title": item.title, "status": item.status, "type": item.type}
        await self.item_repo.update(item_id, status="CANCELED")
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="CANCELED",
            before=before,
            after={"status": "CANCELED"},
        )

    async def _apply_done(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> None:
        """Apply done operation."""
        if not op.ref:
            return
        
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_done", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        before = {"title": item.title, "status": item.status, "type": item.type}
        await self.item_repo.update(item_id, status="DONE")
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="DONE",
            before=before,
            after={"status": "DONE"},
        )

    async def _apply_archive(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> None:
        """Apply archive operation."""
        if not op.ref:
            return
        
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_archive", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        before = {"title": item.title, "status": item.status, "type": item.type}
        await self.item_repo.update(item_id, status="ARCHIVED")
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="ARCHIVED",
            before=before,
            after={"status": "ARCHIVED"},
        )

    async def _apply_unarchive(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> None:
        """Apply unarchive operation."""
        if not op.ref:
            return
        
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_unarchive", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        before = {"title": item.title, "status": item.status, "type": item.type}
        await self.item_repo.update(item_id, status="ACTIVE")
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="UNARCHIVED",
            before=before,
            after={"status": "ACTIVE"},
        )

    async def _apply_pin(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> None:
        """Apply pin operation."""
        if not op.ref:
            return
        
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_pin", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        before = {"title": item.title, "pinned": item.pinned, "type": item.type}
        await self.item_repo.update(item_id, pinned=True)
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="PINNED",
            before=before,
            after={"pinned": True},
        )

    async def _apply_unpin(
        self,
        conversation_id: UUID,
        proposal_id: UUID,
        op: ItemOp,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> None:
        """Apply unpin operation."""
        if not op.ref:
            return
        
        item_id = await self._resolve_item_id(op.ref, conversation_id, confirmed_resolutions)
        if not item_id:
            logger.warning("cannot_resolve_item_for_unpin", ref=op.ref)
            return
        
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return
        
        before = {"title": item.title, "pinned": item.pinned, "type": item.type}
        await self.item_repo.update(item_id, pinned=False)
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="UNPINNED",
            before=before,
            after={"pinned": False},
        )

    async def _resolve_item_id(
        self,
        ref: ItemRef | dict,
        conversation_id: UUID,
        confirmed_resolutions: dict[str, UUID] | None,
    ) -> UUID | None:
        """Resolve an item reference to an item ID."""
        # Handle both ItemRef object and dict
        if isinstance(ref, ItemRef):
            item_ref = ref
        else:
            item_ref = ItemRef(**ref)
        
        if item_ref.type == ItemRefType.ITEM_ID:
            try:
                return UUID(item_ref.value)
            except ValueError:
                return None
        
        # Check confirmed resolutions
        if confirmed_resolutions and item_ref.value in confirmed_resolutions:
            return confirmed_resolutions[item_ref.value]
        
        # For natural references, would need resolver - simplified here
        return None

    async def confirm_time(
        self,
        proposal_id: UUID,
        updates: list,
    ) -> dict:
        """
        Confirm time for a proposal and apply it.
        
        Args:
            proposal_id: The proposal to confirm
            updates: List of TimeUpdateItem with time confirmations
        
        Returns:
            Dict with proposal_id, applied status, and items_affected count
        """
        from app.schemas.enums import ItemRefType
        from app.schemas.proposals import ConfirmTimeResponse
        
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if not proposal:
            raise ProposalNotFoundError(str(proposal_id))
        
        # Verify proposal is in needs_confirmation or ready state
        if proposal.status not in [
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ProposalStatus.READY.value,
        ]:
            raise ProposalNotReadyError(str(proposal_id), proposal.status)
        
        # Load proposal ops
        if not proposal.ops:
            raise ValueError("Proposal has no operations")
        
        payload = LlmProposalPayload(**proposal.ops)
        
        # Apply time updates to ops
        for update_item in updates:
            ref = update_item.ref
            
            # Find matching op
            for op in payload.ops:
                if ref.type == ItemRefType.TEMP_ID and op.temp_id == ref.value:
                    # Update the op's due_at
                    op.due_at = update_item.due_at.isoformat()
                    # Store timezone if provided
                    if not hasattr(op, "timezone"):
                        # Add timezone field dynamically if needed
                        pass
                    logger.info(
                        "time_confirmed_for_op",
                        temp_id=op.temp_id,
                        due_at=op.due_at,
                        timezone=update_item.timezone,
                    )
                    break
        
        # Clear clarifications since they're resolved
        payload.clarifications = []
        payload.needs_confirmation = False
        
        # Update proposal with modified ops
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.READY.value,
            ops=payload.model_dump(mode='json'),
            resolution=proposal.resolution,
        )
        await self.session.commit()
        
        # Now apply the proposal
        from app.schemas.proposals import ApplyProposalRequest
        
        result = await self.apply_proposal(
            ApplyProposalRequest(proposal_id=proposal_id)
        )
        
        return {
            "proposal_id": proposal_id,
            "applied": True,
            "items_affected": result.items_affected,
        }

    async def _cancel_item_by_id(
        self,
        item_id: UUID,
        conversation_id: UUID,
        proposal_id: UUID,
    ) -> bool:
        """Cancel an item by ID and record event."""
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            return False
        
        before = {"title": item.title, "status": item.status, "type": item.type}
        await self.item_repo.update(item_id, status="CANCELED")
        
        await self.item_event_repo.create(
            item_id=item_id,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            event_type="CANCELED",
            before=before,
            after={"status": "CANCELED"},
        )
        return True

    async def get_upcoming_items_context(
        self,
        user_id: UUID,
        reference_time: datetime,
        window_hours: int = 3,
    ) -> ClarificationContext:
        """
        Get upcoming items context for a given reference time.
        
        Args:
            user_id: The user's ID
            reference_time: Center of the time window
            window_hours: Hours before and after reference time
        
        Returns:
            ClarificationContext with upcoming items (tasks with due_at)
        """
        window_start = reference_time - timedelta(hours=window_hours)
        window_end = reference_time + timedelta(hours=window_hours)
        
        items = await self.item_repo.get_items_in_window(
            user_id=user_id,
            window_start=window_start,
            window_end=window_end,
            exclude_statuses=["CANCELED"],
            limit=10,
        )
        
        upcoming_summaries = [
            UpcomingItemSummary(
                item_id=item.id,
                conversation_id=item.conversation_id,
                title=item.title,
                due_at=item.due_at,
                timezone=item.timezone,
                status=ItemStatus(item.status),
                item_type=ItemType(item.type),
            )
            for item in items
            if item.due_at is not None
        ]
        
        return ClarificationContext(
            upcoming_items=upcoming_summaries,
            window_start=window_start,
            window_end=window_end,
        )

    async def detect_conflicts(
        self,
        user_id: UUID,
        target_time: datetime,
        window_minutes: int = 30,
        exclude_item_ids: list[UUID] | None = None,
    ) -> list[UpcomingItemSummary]:
        """
        Detect conflicting items (tasks with due_at) for a proposed time.
        
        Returns list of conflicting item summaries.
        """
        conflicting_items = await self.item_repo.find_conflicting_items(
            user_id=user_id,
            target_time=target_time,
            window_minutes=window_minutes,
            exclude_item_ids=exclude_item_ids,
        )
        
        return [
            UpcomingItemSummary(
                item_id=item.id,
                conversation_id=item.conversation_id,
                title=item.title,
                due_at=item.due_at,
                timezone=item.timezone,
                status=ItemStatus(item.status),
                item_type=ItemType(item.type),
            )
            for item in conflicting_items
            if item.due_at is not None
        ]

    async def generate_alternative_suggestions(
        self,
        user_id: UUID,
        original_time: datetime,
        timezone: str,
        max_suggestions: int = 2,
    ) -> list[TimeSuggestion]:
        """
        Generate alternative time suggestions that avoid conflicts.
        
        Tries: +60min, +90min, next day same time.
        Returns first conflict-free suggestions.
        """
        try:
            tz = ZoneInfo(timezone)
        except Exception:
            tz = ZoneInfo("UTC")
        
        alternatives = [
            (original_time + timedelta(minutes=60), "1 hour later"),
            (original_time + timedelta(minutes=90), "1.5 hours later"),
            (original_time + timedelta(days=1), "Same time tomorrow"),
        ]
        
        suggestions = []
        for alt_time, label in alternatives:
            conflicts = await self.detect_conflicts(
                user_id=user_id,
                target_time=alt_time,
                window_minutes=30,
            )
            
            if not conflicts:
                suggestions.append(
                    TimeSuggestion(
                        due_at=alt_time,
                        timezone=timezone,
                        label=f"{alt_time.astimezone(tz).strftime('%I:%M %p')} ({label})",
                        confidence=0.7,
                    )
                )
                
                if len(suggestions) >= max_suggestions:
                    break
        
        return suggestions

    async def confirm_proposal(
        self,
        proposal_id: UUID,
        request: ConfirmRequest,
        user_id: UUID,
    ) -> ConfirmResponse:
        """
        Confirm a proposal with time updates or conflict resolution.
        
        Handles:
        - apply: Simple due_at fill without conflicts, apply if conflict-free
        - replace_existing: Cancel old task and create new at requested time
        - reschedule_new: Set new time and re-check conflicts
        - cancel_new: Cancel the proposal without creating new task
        """
        proposal = await self.proposal_repo.get_by_id(proposal_id)
        if not proposal:
            raise ProposalNotFoundError(str(proposal_id))
        
        # Check if already processed (idempotency)
        if proposal.status in [
            ProposalStatus.APPLIED.value,
            ProposalStatus.CANCELED.value,
        ]:
            return ConfirmResponse(
                proposal_id=proposal_id,
                status=ProposalStatus(proposal.status),
                applied=proposal.status == ProposalStatus.APPLIED.value,
                items_affected=0,
                items_canceled=0,
                needs_further_confirmation=False,
            )
        
        # Verify proposal is confirmable
        if proposal.status not in [
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ProposalStatus.READY.value,
        ]:
            raise ProposalNotReadyError(str(proposal_id), proposal.status)
        
        # Get conversation for user verification
        conversation = await self.conversation_repo.get_by_id(proposal.conversation_id)
        if not conversation:
            raise ProposalNotFoundError(str(proposal_id))
        
        # Handle cancel_new action
        if request.action == ConfirmAction.CANCEL_NEW:
            return await self._handle_cancel_new(proposal, user_id)
        
        # Load proposal ops
        if not proposal.ops:
            raise ValueError("Proposal has no operations")
        
        payload = LlmProposalPayload(**proposal.ops)
        
        # Build clarification lookup
        clarification_map = {
            c.clarification_id: c
            for c in payload.clarifications
            if c.clarification_id
        }
        
        # Apply updates to ops based on clarification_id
        for update in request.updates:
            if update.clarification_id not in clarification_map:
                raise ClarificationNotFoundError(
                    update.clarification_id, str(proposal_id)
                )
            
            clarification = clarification_map[update.clarification_id]
            
            if clarification.target_temp_id:
                # Find matching op by temp_id
                for op in payload.ops:
                    if op.temp_id == clarification.target_temp_id:
                        if update.due_at:
                            op.due_at = update.due_at.isoformat()
                        break
        
        # Handle replace_existing action
        items_canceled = 0
        if request.action == ConfirmAction.REPLACE_EXISTING:
            items_canceled = await self._handle_replace_existing(
                proposal, payload, clarification_map, user_id
            )
        
        # Handle reschedule_new action
        if request.action == ConfirmAction.RESCHEDULE_NEW:
            result = await self._handle_reschedule_new(
                proposal, payload, clarification_map, request.updates, user_id
            )
            if result.needs_further_confirmation:
                return result
        
        # Check for conflicts before applying (when action is APPLY)
        if request.action == ConfirmAction.APPLY:
            conflict_result = await self._check_and_handle_conflicts(
                proposal, payload, user_id
            )
            if conflict_result:
                return conflict_result
        
        # Clear clarifications and update payload
        payload.clarifications = []
        payload.needs_confirmation = False
        
        # Update proposal ops
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.READY.value,
            ops=payload.model_dump(mode='json'),
            resolution=proposal.resolution,
        )
        await self.session.commit()
        
        # Apply the proposal
        apply_result = await self.apply_proposal(
            ApplyProposalRequest(proposal_id=proposal_id)
        )
        
        return ConfirmResponse(
            proposal_id=proposal_id,
            status=apply_result.status,
            applied=True,
            items_affected=apply_result.items_affected,
            items_canceled=items_canceled,
            needs_further_confirmation=False,
        )

    async def _handle_cancel_new(
        self,
        proposal,
        user_id: UUID,
    ) -> ConfirmResponse:
        """Handle cancel_new action."""
        await self.proposal_repo.update_status(
            proposal.id,
            ProposalStatus.CANCELED.value,
            error_message="Canceled by user",
        )
        await self.session.commit()
        
        # Publish event
        event_bus = get_event_bus()
        await event_bus.publish(
            WsEvent(
                type=EventType.PROPOSAL_CANCELED,
                conversation_id=proposal.conversation_id,
                proposal_id=proposal.id,
                version=proposal.version,
                data={"reason": "user_canceled"},
            )
        )
        
        logger.info(
            "proposal_canceled",
            proposal_id=str(proposal.id),
        )
        
        return ConfirmResponse(
            proposal_id=proposal.id,
            status=ProposalStatus.CANCELED,
            applied=False,
            items_affected=0,
            items_canceled=0,
            needs_further_confirmation=False,
        )

    async def _handle_replace_existing(
        self,
        proposal,
        payload: LlmProposalPayload,
        clarification_map: dict[str, Clarification],
        user_id: UUID,
    ) -> int:
        """
        Handle replace_existing action by canceling conflicting items.
        
        Returns number of items canceled.
        """
        items_canceled = 0
        
        for clarification in payload.clarifications:
            if (
                clarification.field == ClarificationField.CONFLICT
                and clarification.conflict
            ):
                existing_item_id = clarification.conflict.existing_item.item_id
                success = await self._cancel_item_by_id(
                    item_id=existing_item_id,
                    conversation_id=proposal.conversation_id,
                    proposal_id=proposal.id,
                )
                if success:
                    items_canceled += 1
                    logger.info(
                        "replaced_existing_item",
                        item_id=str(existing_item_id),
                        proposal_id=str(proposal.id),
                    )
        
        return items_canceled

    async def _handle_reschedule_new(
        self,
        proposal,
        payload: LlmProposalPayload,
        clarification_map: dict[str, Clarification],
        updates: list[ConfirmUpdate],
        user_id: UUID,
    ) -> ConfirmResponse:
        """
        Handle reschedule_new action.
        
        Re-checks for conflicts after applying new time.
        """
        conversation = await self.conversation_repo.get_by_id(proposal.conversation_id)
        if not conversation:
            raise ProposalNotFoundError(str(proposal.id))
        
        # Resolve user timezone for correct time interpretation
        from app.db.repositories.user_repo import UserRepository
        user_repo = UserRepository(self.session)
        user_obj = await user_repo.get_by_id(user_id)
        user_tz_name = (user_obj.timezone if user_obj and user_obj.timezone else "UTC")
        try:
            user_tz = ZoneInfo(user_tz_name)
        except Exception:
            user_tz = ZoneInfo("UTC")

        # Check for new conflicts after rescheduling
        new_clarifications = []
        
        for op in payload.ops:
            if op.op == OpType.CREATE and op.due_at:
                due_at = parse_natural_time(op.due_at, tz=user_tz_name)
                if due_at:
                    due_at = ensure_utc(due_at)
                    conflicts = await self.detect_conflicts(
                        user_id=conversation.user_id,
                        target_time=due_at,
                        window_minutes=30,
                    )
                    
                    if conflicts:
                        # Still has conflicts, generate new clarification
                        context = await self.get_upcoming_items_context(
                            user_id=conversation.user_id,
                            reference_time=due_at,
                        )
                        
                        suggestions = await self.generate_alternative_suggestions(
                            user_id=conversation.user_id,
                            original_time=due_at,
                            timezone=op.suggested_timezone or user_tz_name,
                        )
                        
                        # Format display time in user-local timezone
                        display_time = due_at.astimezone(user_tz).strftime('%I:%M %p')
                        clarification = Clarification(
                            clarification_id=generate_clarification_id(),
                            field=ClarificationField.CONFLICT,
                            target_temp_id=op.temp_id,
                            message=f"'{op.title}' at {display_time} conflicts with '{conflicts[0].title}'",
                            suggestions=suggestions,
                            context=context,
                            conflict=ConflictInfo(
                                existing_item=conflicts[0],
                                proposed_due_at=due_at,
                                window_minutes=30,
                            ),
                            available_actions=["replace_existing", "reschedule_new", "cancel_new"],
                        )
                        new_clarifications.append(clarification)
        
        if new_clarifications:
            # Update payload with new clarifications
            payload.clarifications = new_clarifications
            payload.needs_confirmation = True
            
            await self.proposal_repo.update_status(
                proposal.id,
                ProposalStatus.NEEDS_CONFIRMATION.value,
                ops=payload.model_dump(mode='json'),
            )
            await self.session.commit()
            
            # Publish event
            event_bus = get_event_bus()
            await event_bus.publish(
                WsEvent(
                    type=EventType.PROPOSAL_NEEDS_CONFIRMATION,
                    conversation_id=proposal.conversation_id,
                    proposal_id=proposal.id,
                    version=proposal.version,
                    data={
                        "clarifications": [
                            c.model_dump(mode='json') for c in new_clarifications
                        ],
                    },
                )
            )
            
            return ConfirmResponse(
                proposal_id=proposal.id,
                status=ProposalStatus.NEEDS_CONFIRMATION,
                applied=False,
                items_affected=0,
                needs_further_confirmation=True,
                clarifications=new_clarifications,
            )
        
        # No conflicts, return with needs_further_confirmation=False
        return ConfirmResponse(
            proposal_id=proposal.id,
            status=ProposalStatus.READY,
            applied=False,
            items_affected=0,
            needs_further_confirmation=False,
        )

    async def _check_and_handle_conflicts(
        self,
        proposal,
        payload: LlmProposalPayload,
        user_id: UUID,
    ) -> ConfirmResponse | None:
        """
        Check for conflicts when action=apply.
        
        Returns ConfirmResponse if conflicts found, None otherwise.
        """
        conversation = await self.conversation_repo.get_by_id(proposal.conversation_id)
        if not conversation:
            return None
        
        # Resolve user timezone for correct time interpretation
        from app.db.repositories.user_repo import UserRepository
        user_repo = UserRepository(self.session)
        user_obj = await user_repo.get_by_id(user_id)
        user_tz_name = (user_obj.timezone if user_obj and user_obj.timezone else "UTC")
        try:
            user_tz = ZoneInfo(user_tz_name)
        except Exception:
            user_tz = ZoneInfo("UTC")

        conflict_clarifications = []
        
        for op in payload.ops:
            if op.op == OpType.CREATE and op.due_at:
                due_at = parse_natural_time(op.due_at, tz=user_tz_name)
                if due_at:
                    due_at = ensure_utc(due_at)
                    conflicts = await self.detect_conflicts(
                        user_id=conversation.user_id,
                        target_time=due_at,
                        window_minutes=30,
                    )
                    
                    if conflicts:
                        context = await self.get_upcoming_items_context(
                            user_id=conversation.user_id,
                            reference_time=due_at,
                        )
                        
                        suggestions = await self.generate_alternative_suggestions(
                            user_id=conversation.user_id,
                            original_time=due_at,
                            timezone=op.suggested_timezone or user_tz_name,
                        )
                        
                        existing = conflicts[0]
                        # Format display time in user-local timezone, NEVER raw UTC
                        due_str = existing.due_at.astimezone(user_tz).strftime('%I:%M %p') if existing.due_at else "unknown time"
                        clarification = Clarification(
                            clarification_id=generate_clarification_id(),
                            field=ClarificationField.CONFLICT,
                            target_temp_id=op.temp_id,
                            message=f"You already have '{existing.title}' at {due_str}. Do you want to cancel it and schedule '{op.title}'?",
                            suggestions=suggestions,
                            context=context,
                            conflict=ConflictInfo(
                                existing_item=existing,
                                proposed_due_at=due_at,
                                window_minutes=30,
                            ),
                            available_actions=["replace_existing", "reschedule_new", "cancel_new"],
                        )
                        conflict_clarifications.append(clarification)
        
        if conflict_clarifications:
            # Update payload with conflict clarifications
            payload.clarifications = conflict_clarifications
            payload.needs_confirmation = True
            
            await self.proposal_repo.update_status(
                proposal.id,
                ProposalStatus.NEEDS_CONFIRMATION.value,
                ops=payload.model_dump(mode='json'),
            )
            await self.session.commit()
            
            # Publish event
            event_bus = get_event_bus()
            await event_bus.publish(
                WsEvent(
                    type=EventType.PROPOSAL_NEEDS_CONFIRMATION,
                    conversation_id=proposal.conversation_id,
                    proposal_id=proposal.id,
                    version=proposal.version,
                    data={
                        "clarifications": [
                            c.model_dump(mode='json') for c in conflict_clarifications
                        ],
                    },
                )
            )
            
            return ConfirmResponse(
                proposal_id=proposal.id,
                status=ProposalStatus.NEEDS_CONFIRMATION,
                applied=False,
                items_affected=0,
                needs_further_confirmation=True,
                clarifications=conflict_clarifications,
            )
        
        return None
