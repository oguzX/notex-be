"""Proposal repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.proposal import Proposal


class ProposalRepository:
    """Repository for proposal database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        conversation_id: UUID,
        message_id: UUID,
        version: int,
        status: str = "queued",
    ) -> Proposal:
        """Create a new proposal."""
        proposal = Proposal(
            conversation_id=conversation_id,
            message_id=message_id,
            version=version,
            status=status,
        )
        self.session.add(proposal)
        await self.session.flush()
        await self.session.refresh(proposal)
        return proposal

    async def get_by_id(self, proposal_id: UUID) -> Proposal | None:
        """Get proposal by ID."""
        result = await self.session.execute(
            select(Proposal).where(Proposal.id == proposal_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        proposal_id: UUID,
        status: str,
        ops: dict | None = None,
        resolution: dict | None = None,
        error_message: str | None = None,
        error_details: dict | None = None,
    ) -> Proposal:
        """Update proposal status and optional fields."""
        proposal = await self.get_by_id(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        proposal.status = status
        if ops is not None:
            proposal.ops = ops
        if resolution is not None:
            proposal.resolution = resolution
        if error_message is not None:
            proposal.error_message = error_message
        if error_details is not None:
            proposal.error_details = error_details
        
        await self.session.flush()
        await self.session.refresh(proposal)
        return proposal

    async def get_latest_actionable(
        self,
        conversation_id: UUID,
    ) -> Proposal | None:
        """Return the most recent proposal with an approvable status.

        Approvable statuses: ready, needs_confirmation.
        """
        result = await self.session.execute(
            select(Proposal)
            .where(
                Proposal.conversation_id == conversation_id,
                Proposal.status.in_(["ready", "needs_confirmation"]),
            )
            .order_by(Proposal.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int | None = None,
    ) -> list[Proposal]:
        """List proposals for a conversation."""
        query = (
            select(Proposal)
            .where(Proposal.conversation_id == conversation_id)
            .order_by(Proposal.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())
