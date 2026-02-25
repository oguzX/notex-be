"""Proposal status management service."""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.proposal_repo import ProposalRepository
from app.schemas.enums import ProposalStatus
from app.schemas.proposals import LlmProposalPayload, ProposalResolution

logger = structlog.get_logger(__name__)


class ProposalStatusManager:
    """
    Service for managing proposal persistence and status updates.

    Encapsulates all proposal database operations, providing
    a clean interface for updating proposal status and data.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize ProposalStatusManager.

        Args:
            session: Database session
        """
        self.session = session
        self.proposal_repo = ProposalRepository(session)

    async def update_to_running(self, proposal_id: UUID) -> None:
        """
        Update proposal status to RUNNING.

        Args:
            proposal_id: Proposal ID
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.RUNNING.value,
        )
        await self.session.commit()
        logger.info("proposal_status_updated", proposal_id=str(proposal_id), status="running")

    async def update_to_failed(
        self,
        proposal_id: UUID,
        error_message: str,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        """
        Update proposal status to FAILED.

        Args:
            proposal_id: Proposal ID
            error_message: Error message
            error_details: Optional error details
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.FAILED.value,
            error_message=error_message,
            error_details=error_details,
        )
        await self.session.commit()
        logger.error("proposal_status_updated", proposal_id=str(proposal_id), status="failed", error=error_message)

    async def update_to_stale(
        self,
        proposal_id: UUID,
        payload: LlmProposalPayload,
        resolution: ProposalResolution | None = None,
    ) -> None:
        """
        Update proposal status to STALE.

        Args:
            proposal_id: Proposal ID
            payload: LLM proposal payload
            resolution: Optional resolution data
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.STALE.value,
            ops=payload.model_dump(mode="json"),
            resolution=resolution.model_dump(mode="json") if resolution else None,
        )
        await self.session.commit()
        logger.warning("proposal_status_updated", proposal_id=str(proposal_id), status="stale")

    async def update_to_needs_confirmation(
        self,
        proposal_id: UUID,
        payload: LlmProposalPayload,
        resolution: ProposalResolution | None = None,
    ) -> None:
        """
        Update proposal status to NEEDS_CONFIRMATION.

        Args:
            proposal_id: Proposal ID
            payload: LLM proposal payload
            resolution: Optional resolution data
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.NEEDS_CONFIRMATION.value,
            ops=payload.model_dump(mode="json"),
            resolution=resolution.model_dump(mode="json") if resolution else None,
        )
        await self.session.commit()
        logger.info("proposal_status_updated", proposal_id=str(proposal_id), status="needs_confirmation")

    async def update_to_ready(
        self,
        proposal_id: UUID,
        payload: LlmProposalPayload,
        resolution: ProposalResolution | None = None,
    ) -> None:
        """
        Update proposal status to READY.

        Args:
            proposal_id: Proposal ID
            payload: LLM proposal payload
            resolution: Optional resolution data
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.READY.value,
            ops=payload.model_dump(mode="json"),
            resolution=resolution.model_dump(mode="json") if resolution else None,
        )
        await self.session.commit()
        logger.info("proposal_status_updated", proposal_id=str(proposal_id), status="ready")

    async def update_to_applied(
        self,
        proposal_id: UUID,
        payload: LlmProposalPayload | None = None,
        resolution: ProposalResolution | None = None,
    ) -> None:
        """
        Update proposal status to APPLIED.

        Args:
            proposal_id: Proposal ID
            payload: Optional LLM proposal payload
            resolution: Optional resolution data
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.APPLIED.value,
            ops=payload.model_dump(mode="json") if payload else None,
            resolution=resolution.model_dump(mode="json") if resolution else None,
        )
        await self.session.commit()
        logger.info("proposal_status_updated", proposal_id=str(proposal_id), status="applied")

    async def update_to_canceled(self, proposal_id: UUID) -> None:
        """
        Update proposal status to CANCELED.

        Args:
            proposal_id: Proposal ID
        """
        await self.proposal_repo.update_status(
            proposal_id,
            ProposalStatus.CANCELED.value,
        )
        await self.session.commit()
        logger.info("proposal_status_updated", proposal_id=str(proposal_id), status="canceled")
