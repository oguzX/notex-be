"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.schemas.proposals import LlmProposalPayload


class BaseLLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def generate_proposal(
        self,
        messages_context: list[dict[str, str]],
        tasks_snapshot: list[dict[str, Any]],
        timezone: str = "UTC",
        auto_apply: bool = True,
        reference_dt_utc: datetime | None = None,
    ) -> LlmProposalPayload:
        """
        Generate a task proposal from message context.
        
        Args:
            messages_context: Recent conversation messages
            tasks_snapshot: Current active tasks
            timezone: User timezone for time parsing
            auto_apply: Whether proposal will be auto-applied
            reference_dt_utc: Reference datetime in UTC (typically message.created_at)
        
        Returns:
            LlmProposalPayload with operations
        """
        pass
