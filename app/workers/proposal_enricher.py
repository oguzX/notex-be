"""Proposal enrichment utilities for time enforcement and conflict detection."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

from app.db.repositories.item_repo import ItemRepository
from app.schemas.enums import (
    ClarificationField,
    ItemRefType,
    ItemStatus,
    ItemType,
    OpType,
)
from app.schemas.proposals import (
    Clarification,
    ClarificationContext,
    ConflictInfo,
    ItemRef,
    LlmProposalPayload,
    TimeSuggestion,
    UpcomingItemSummary,
)
from app.utils.ids import generate_clarification_id
from app.utils.time import ensure_utc, parse_natural_time

logger = structlog.get_logger(__name__)


class ProposalEnricher:
    """
    Service for enriching proposals with clarifications.

    Handles:
    - Time confirmation enforcement (auto_apply=false)
    - Conflict detection
    - Context enrichment with upcoming items
    """

    def __init__(self, item_repo: ItemRepository):
        """
        Initialize ProposalEnricher.

        Args:
            item_repo: Item repository for querying items
        """
        self.item_repo = item_repo

    def enforce_time_confirmation(
        self,
        payload: LlmProposalPayload,
        timezone: str,
    ) -> LlmProposalPayload:
        """
        Enforce time confirmation for create ops with missing due_at.

        When auto_apply=false, any create op without due_at requires confirmation.
        Ensures needs_confirmation flag and clarifications are set properly.

        Args:
            payload: LLM proposal payload
            timezone: User timezone

        Returns:
            Updated payload with time clarifications
        """
        # Find create ops with missing due_at (skip NOTEs — they don't need scheduling)
        missing_time_ops = []
        for op in payload.ops:
            if op.op == OpType.CREATE and not op.due_at and op.item_type != ItemType.NOTE:
                missing_time_ops.append(op)

        if not missing_time_ops:
            return payload

        # Force needs_confirmation
        payload.needs_confirmation = True

        # Build lookup for existing clarifications
        existing_by_temp_id = {
            c.target_temp_id: c for c in payload.clarifications if c.target_temp_id
        }

        existing_by_op_ref = {}
        for c in payload.clarifications:
            if c.op_ref:
                existing_by_op_ref[(c.op_ref.type, c.op_ref.value)] = c

        for op in missing_time_ops:
            temp_id = op.temp_id or "unknown"

            # Skip if clarification already exists
            if temp_id in existing_by_temp_id:
                continue

            op_ref = ItemRef(type=ItemRefType.TEMP_ID, value=temp_id)
            if (op_ref.type, op_ref.value) in existing_by_op_ref:
                continue

            # Generate fallback suggestion
            suggestions = self._generate_time_suggestions(op, timezone)

            clarification = Clarification(
                clarification_id=generate_clarification_id(),
                field=ClarificationField.DUE_AT,
                target_temp_id=temp_id,
                message=f"When would you like to schedule '{op.title or 'this task'}'?",
                suggestions=suggestions,
                op_ref=op_ref,
            )

            payload.clarifications.append(clarification)

        logger.info(
            "time_confirmation_enforced",
            missing_ops=len(missing_time_ops),
            clarifications=len(payload.clarifications),
        )

        return payload

    def _generate_time_suggestions(
        self,
        op: Any,
        timezone: str,
    ) -> list[TimeSuggestion]:
        """Generate time suggestions for an operation."""
        try:
            tz = ZoneInfo(timezone)
        except Exception:
            tz = ZoneInfo("UTC")

        now = datetime.now(tz)

        suggestions = []

        # Check if LLM provided suggestions in op
        if op.suggested_due_at:
            suggestions.append(
                TimeSuggestion(
                    due_at=op.suggested_due_at,
                    timezone=op.suggested_timezone or timezone,
                    label=f"{op.suggested_due_at.strftime('%I:%M %p')} (suggested)",
                    confidence=op.suggested_confidence or 0.7,
                )
            )
        else:
            # Use fallback: today or tomorrow at 7 PM
            if now.hour < 19:
                suggested_time = now.replace(hour=19, minute=0, second=0, microsecond=0)
                label = "This evening at 7 PM (suggested)"
            else:
                suggested_time = (now + timedelta(days=1)).replace(
                    hour=19, minute=0, second=0, microsecond=0
                )
                label = "Tomorrow evening at 7 PM (suggested)"

            suggestions.append(
                TimeSuggestion(
                    due_at=suggested_time,
                    timezone=timezone,
                    label=label,
                    confidence=0.3,
                )
            )

        return suggestions

    async def enrich_with_upcoming_context(
        self,
        payload: LlmProposalPayload,
        user_id: UUID,
        timezone: str,
    ) -> LlmProposalPayload:
        """
        Enrich clarifications with upcoming items context.

        For each clarification, adds nearby upcoming items to help users decide.

        Args:
            payload: LLM proposal payload
            user_id: User ID
            timezone: User timezone

        Returns:
            Updated payload with enriched clarifications
        """
        try:
            tz = ZoneInfo(timezone)
        except Exception:
            tz = ZoneInfo("UTC")

        for clarification in payload.clarifications:
            # Get reference time from suggestions or use now
            reference_time = datetime.now(tz)
            if clarification.suggestions:
                reference_time = clarification.suggestions[0].due_at
            reference_time = ensure_utc(reference_time)

            # Get upcoming items in ±3 hour window (UTC)
            window_start = reference_time - timedelta(hours=3)
            window_end = reference_time + timedelta(hours=3)

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
                    item_type=ItemType(item.type),
                    due_at=item.due_at,
                    timezone=item.timezone,
                    status=ItemStatus(item.status),
                )
                for item in items
                if item.due_at is not None
            ]

            clarification.context = ClarificationContext(
                upcoming_items=upcoming_summaries,
                window_start=window_start,
                window_end=window_end,
            )

        return payload

    async def detect_and_add_conflict_clarifications(
        self,
        payload: LlmProposalPayload,
        user_id: UUID,
        timezone: str,
    ) -> LlmProposalPayload:
        """
        Detect scheduling conflicts for create ops and add conflict clarifications.

        For each create op with due_at, checks for conflicting items within ±30 min.
        If conflicts found, adds clarification with conflict field.

        Args:
            payload: LLM proposal payload
            user_id: User ID
            timezone: User timezone

        Returns:
            Updated payload with conflict clarifications
        """
        try:
            tz = ZoneInfo(timezone)
        except Exception:
            tz = ZoneInfo("UTC")

        conflict_clarifications = []

        for op in payload.ops:
            if op.op != OpType.CREATE or not op.due_at:
                continue

            # Parse due_at in user timezone, then normalize to UTC
            due_at = parse_natural_time(op.due_at, tz=timezone)
            if not due_at:
                continue
            due_at = ensure_utc(due_at)

            # Find conflicting items
            conflicting_items = await self.item_repo.find_conflicting_items(
                user_id=user_id,
                target_time=due_at,
                window_minutes=30,
            )

            if not conflicting_items:
                continue

            existing_item = conflicting_items[0]

            # Generate conflict clarification
            clarification = await self._build_conflict_clarification(
                op=op,
                existing_item=existing_item,
                due_at=due_at,
                user_id=user_id,
                timezone=timezone,
                tz=tz,
            )

            conflict_clarifications.append(clarification)

        if conflict_clarifications:
            payload.needs_confirmation = True
            payload.clarifications.extend(conflict_clarifications)

            logger.info(
                "conflict_clarifications_added",
                conflict_count=len(conflict_clarifications),
            )

        return payload

    async def _build_conflict_clarification(
        self,
        op: Any,
        existing_item: Any,
        due_at: datetime,
        user_id: UUID,
        timezone: str,
        tz: ZoneInfo,
    ) -> Clarification:
        """Build a conflict clarification."""
        # Get context for this conflict
        window_start = due_at - timedelta(hours=3)
        window_end = due_at + timedelta(hours=3)

        context_items = await self.item_repo.get_items_in_window(
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
                item_type=ItemType(item.type),
                due_at=item.due_at,
                timezone=item.timezone,
                status=ItemStatus(item.status),
            )
            for item in context_items
            if item.due_at is not None
        ]

        context = ClarificationContext(
            upcoming_items=upcoming_summaries,
            window_start=window_start,
            window_end=window_end,
        )

        # Generate alternative suggestions
        suggestions = await self._generate_conflict_free_suggestions(
            user_id=user_id,
            original_time=due_at,
            timezone=timezone,
        )

        existing_due_at = existing_item.due_at or due_at

        existing_summary = UpcomingItemSummary(
            item_id=existing_item.id,
            conversation_id=existing_item.conversation_id,
            title=existing_item.title,
            item_type=ItemType(existing_item.type),
            due_at=existing_due_at,
            timezone=existing_item.timezone,
            status=ItemStatus(existing_item.status),
        )

        # Format display time in user-local timezone
        if existing_item.due_at:
            existing_local = existing_item.due_at.astimezone(tz)
            due_str = existing_local.strftime("%I:%M %p")
        else:
            due_str = "the same time"

        return Clarification(
            clarification_id=generate_clarification_id(),
            field=ClarificationField.CONFLICT,
            target_temp_id=op.temp_id,
            message=f"You already have '{existing_item.title}' at {due_str}. Do you want to cancel it and schedule '{op.title}'?",
            suggestions=suggestions,
            context=context,
            conflict=ConflictInfo(
                existing_item=existing_summary,
                proposed_due_at=due_at,
                window_minutes=30,
            ),
            available_actions=["replace_existing", "reschedule_new", "cancel_new"],
        )

    async def _generate_conflict_free_suggestions(
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

        Args:
            user_id: User ID
            original_time: Original conflicting time
            timezone: User timezone
            max_suggestions: Maximum number of suggestions

        Returns:
            List of conflict-free time suggestions
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
            conflicts = await self.item_repo.find_conflicting_items(
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
