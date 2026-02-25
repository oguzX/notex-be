"""LLM router service for dual-mode execution (Ops vs MCP Tools)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from app.llm.factory import get_llm_provider
from app.llm.intent_classifier import IntentType, classify_intent
from app.schemas.proposals import LlmProposalPayload

logger = structlog.get_logger(__name__)


class LlmRouterService:
    """Routes LLM requests between Ops Mode and Tool Mode based on intent."""
    
    def __init__(self) -> None:
        self.provider = get_llm_provider()
    
    async def process_message(
        self,
        messages_context: list[dict[str, str]],
        tasks_snapshot: list[dict[str, Any]],
        timezone: str = "Europe/Istanbul",
        auto_apply: bool = True,
        reference_dt_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Process message with automatic mode routing.
        
        Args:
            messages_context: Recent conversation messages.
            tasks_snapshot: Current task state for context.
            timezone: User's timezone.
            auto_apply: Whether to auto-apply proposals.
            reference_dt_utc: Reference datetime for relative date parsing.
            
        Returns:
            Dictionary with:
                - mode: "ops" or "tool"
                - For ops mode: proposal (LlmProposalPayload)
                - For tool mode: text, tool_calls
        """
        # Classify intent from the last user message
        last_message = messages_context[-1] if messages_context else {}
        user_message = last_message.get("content", "")
        
        intent = classify_intent(user_message)
        
        logger.info(
            "llm_router_intent_classified",
            intent=intent.value,
            message_preview=user_message[:100],
        )
        
        if intent == IntentType.TOOL_MODE:
            # MCP Tool Mode: weather, FX, etc.
            return await self.process_tool_mode(messages_context)
        else:
            # Ops Mode: task/note management
            return await self.process_ops_mode(
                messages_context,
                tasks_snapshot,
                timezone,
                auto_apply,
                reference_dt_utc,
            )
    
    async def process_ops_mode(
        self,
        messages_context: list[dict[str, str]],
        tasks_snapshot: list[dict[str, Any]],
        timezone: str,
        auto_apply: bool,
        reference_dt_utc: datetime | None,
    ) -> dict[str, Any]:
        """Process in Ops Mode (traditional task/note operations)."""
        logger.info("llm_router_ops_mode_start")
        
        proposal = await self.provider.generate_proposal(
            messages_context=messages_context,
            tasks_snapshot=tasks_snapshot,
            timezone=timezone,
            auto_apply=auto_apply,
            reference_dt_utc=reference_dt_utc,
        )
        
        logger.info(
            "llm_router_ops_mode_complete",
            ops_count=len(proposal.ops) if proposal.ops else 0,
        )
        
        return {
            "mode": "ops",
            "proposal": proposal,
        }
    
    async def process_tool_mode(
        self,
        messages_context: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Process in Tool Mode (MCP tools via Responses API)."""
        logger.info("llm_router_tool_mode_start")
        
        # Check if provider supports tool mode
        if not hasattr(self.provider, 'generate_tool_response'):
            logger.warning("llm_router_tool_mode_unsupported")
            # Fallback: return a simple response
            return {
                "mode": "tool",
                "text": "Tool mode is not supported by the current LLM provider.",
                "tool_calls": [],
            }
        
        result = await self.provider.generate_tool_response(  # type: ignore
            messages_context=messages_context,
        )
        
        logger.info(
            "llm_router_tool_mode_complete",
            tool_calls_count=len(result.get("tool_calls", [])),
        )
        
        return {
            "mode": "tool",
            **result,
        }
