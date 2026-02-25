"""Resolver service for matching natural references to items."""

from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.item import Item
from app.db.repositories.item_repo import ItemRepository
from app.schemas.proposals import (
    ItemOp,
    ItemRef,
    ItemResolution,
    ProposalResolution,
    ResolutionCandidate,
)
from app.schemas.enums import ItemRefType
from app.utils.similarity import fuzzy_similarity
from app.utils.time import parse_datetime_from_text, time_distance_minutes

logger = structlog.get_logger(__name__)


class ResolverService:
    """Service for resolving natural language item references."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.item_repo = ItemRepository(session)
        self.settings = get_settings()

    async def resolve_operations(
        self,
        conversation_id: UUID,
        ops: list[ItemOp],
        timezone: str = "UTC",
        reference_dt_utc: datetime | None = None,
    ) -> ProposalResolution:
        """
        Resolve all item references in operations.
        
        Args:
            conversation_id: The conversation ID
            ops: List of item operations
            timezone: Target timezone for time parsing
            reference_dt_utc: Reference datetime in UTC for relative time parsing
        
        Returns:
            Resolution data and whether confirmation is needed.
        """
        resolutions: list[ItemResolution] = []
        needs_confirmation = False
        
        for op in ops:
            if op.ref:
                resolution = await self._resolve_ref(
                    conversation_id,
                    op.ref,
                    timezone,
                    reference_dt_utc,
                )
                resolutions.append(resolution)
                
                if resolution.requires_confirmation:
                    needs_confirmation = True
        
        return ProposalResolution(
            resolutions=resolutions,
            needs_confirmation=needs_confirmation,
        )

    async def _resolve_ref(
        self,
        conversation_id: UUID,
        ref: ItemRef,
        timezone: str,
        reference_dt_utc: datetime | None = None,
    ) -> ItemResolution:
        """Resolve a single item reference."""
        # If already an item_id, no resolution needed
        if ref.type == ItemRefType.ITEM_ID:
            try:
                item_id = UUID(ref.value)
                return ItemResolution(
                    ref=ref,
                    resolved_item_id=item_id,
                    confidence=1.0,
                    candidates=[],
                    requires_confirmation=False,
                )
            except ValueError:
                pass
        
        # Natural reference resolution
        if ref.type == ItemRefType.NATURAL:
            return await self._resolve_natural(
                conversation_id, ref, timezone, reference_dt_utc
            )
        
        # temp_id or unresolvable
        return ItemResolution(
            ref=ref,
            resolved_item_id=None,
            confidence=0.0,
            candidates=[],
            requires_confirmation=True,
        )

    async def _resolve_natural(
        self,
        conversation_id: UUID,
        ref: ItemRef,
        timezone: str,
        reference_dt_utc: datetime | None = None,
    ) -> ItemResolution:
        """
        Resolve natural language reference.
        
        Strategy:
        1. Try to parse time from reference text using robust parser
        2. If time found, search items by time window
        3. Score candidates by time proximity + text similarity + recency
        4. Return best match or require confirmation
        """
        candidates: list[ResolutionCandidate] = []
        
        # Try parsing time with robust parser
        if reference_dt_utc is not None:
            parsed_time = parse_datetime_from_text(
                ref.value,
                reference_dt_utc,
                timezone,
                languages=["tr", "en"],
            )
        else:
            # Fallback to legacy parser
            from app.utils.time import parse_natural_time
            parsed_time = parse_natural_time(ref.value, tz=timezone)
        
        if parsed_time:
            # Search by time window
            items = await self.item_repo.search_by_time_window(
                conversation_id,
                parsed_time,
                self.settings.RESOLVER_TIME_WINDOW_MINUTES,
            )
            
            # Score candidates
            scored_candidates = []
            for item in items:
                score = self._score_item(ref.value, item, parsed_time)
                scored_candidates.append((item, score))
            
            # Sort by score
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            
            # Build candidate list
            for item, score in scored_candidates[: self.settings.RESOLVER_MAX_CANDIDATES]:
                candidates.append(
                    ResolutionCandidate(
                        item_id=item.id,
                        score=score,
                        title=item.title,
                        due_at=item.due_at,
                    )
                )
        else:
            # No time parsed, search by text similarity only
            items = await self.item_repo.list_by_conversation(
                conversation_id,
                status="ACTIVE",
            )
            
            scored_candidates = []
            for item in items:
                score = self._score_item_by_text(ref.value, item)
                if score > 0.3:  # Minimum threshold
                    scored_candidates.append((item, score))
            
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            
            for item, score in scored_candidates[: self.settings.RESOLVER_MAX_CANDIDATES]:
                candidates.append(
                    ResolutionCandidate(
                        item_id=item.id,
                        score=score,
                        title=item.title,
                        due_at=item.due_at,
                    )
                )
        
        # Determine if confirmation needed
        if not candidates:
            return ItemResolution(
                ref=ref,
                resolved_item_id=None,
                confidence=0.0,
                candidates=[],
                requires_confirmation=True,
            )
        
        best = candidates[0]
        second_best_score = candidates[1].score if len(candidates) > 1 else 0.0
        
        # Require confirmation if:
        # - Best score below threshold
        # - Second best is close (ambiguous)
        requires_confirmation = (
            best.score < self.settings.RESOLVER_CONFIDENCE_THRESHOLD
            or (second_best_score > 0 and best.score - second_best_score < 0.15)
        )
        
        return ItemResolution(
            ref=ref,
            resolved_item_id=best.item_id if not requires_confirmation else None,
            confidence=best.score,
            candidates=candidates,
            requires_confirmation=requires_confirmation,
        )

    def _score_item(
        self,
        query: str,
        item: Item,
        target_time: datetime,
    ) -> float:
        """
        Score an item candidate.
        
        Combines:
        - Time proximity (0-1)
        - Text similarity (0-1)
        - Recency boost (0-1)
        """
        score = 0.0
        
        # Time proximity
        if item.due_at:
            distance = time_distance_minutes(item.due_at, target_time)
            time_score = max(
                0.0,
                1.0 - (distance / self.settings.RESOLVER_TIME_WINDOW_MINUTES),
            )
            score += time_score * 0.5
        
        # Text similarity
        text_score = fuzzy_similarity(query, item.title)
        score += text_score * 0.4
        
        # Recency boost (newer items slightly preferred)
        # Simple: items created in last hour get +0.1
        recency_score = 0.1
        score += recency_score
        
        return min(score, 1.0)

    def _score_item_by_text(self, query: str, item: Item) -> float:
        """Score item by text similarity only."""
        return fuzzy_similarity(query, item.title)
