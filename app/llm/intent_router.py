"""Intent Router Agent - Context-aware message routing.

This module implements an intelligent router that decides how to handle
incoming user messages based on conversation context and active proposals.

Unlike the old regex-based system, this router:
- Uses LLM for context-aware decisions
- Understands proposal state (needs_confirmation, etc.)
- Can distinguish between modifications and new requests
- Provides confidence scores and reasoning
"""

from typing import Any

import structlog
from pydantic import ValidationError

from app.core.config import get_settings
from app.llm.errors import (
    LlmProviderCallError,
    LlmProviderConfigError,
    LlmProviderResponseError,
)
from app.schemas.intents import RouterDecision, RouterDecisionType

logger = structlog.get_logger(__name__)


class IntentRouterAgent:
    """
    A2A-based Intent Router Agent.

    Responsibilities:
    - Route user messages based on active proposal context
    - Provide context-aware intent classification
    - Use structured output for reliable schema enforcement
    - Fail-safe to NEW_OPERATION if LLM cannot decide

    This agent runs BEFORE the main LLM pipeline to efficiently
    handle simple cases like confirmations/rejections.
    """

    def __init__(self, provider: str | None = None):
        """
        Initialize Intent Router Agent.

        Args:
            provider: LLM provider to use ('openai' or 'gemini').
                     If None, uses settings.LLM_PROVIDER
        """
        settings = get_settings()
        self.provider_name = provider or settings.LLM_PROVIDER
        self.model = self._get_model()
        self.api_key = self._get_api_key()

        # Validate configuration
        if not self.api_key:
            raise LlmProviderConfigError(
                f"{self.provider_name.upper()}_API_KEY is not configured",
                details={"provider": self.provider_name},
            )

    def _get_model(self) -> str:
        """Get model name for the provider."""
        settings = get_settings()
        if self.provider_name == "openai":
            return settings.OPENAI_MODEL
        elif self.provider_name == "gemini":
            return settings.GEMINI_MODEL
        else:
            raise LlmProviderConfigError(
                f"Unknown provider: {self.provider_name}",
                details={"provider": self.provider_name},
            )

    def _get_api_key(self) -> str:
        """Get API key for the provider."""
        settings = get_settings()
        if self.provider_name == "openai":
            return settings.OPENAI_API_KEY
        elif self.provider_name == "gemini":
            return settings.GEMINI_API_KEY
        else:
            raise LlmProviderConfigError(
                f"Unknown provider: {self.provider_name}",
                details={"provider": self.provider_name},
            )

    async def route(
        self,
        user_message: str,
        active_proposal: dict[str, Any] | None = None,
    ) -> RouterDecision:
        """
        Route user message based on context.

        Args:
            user_message: The user's message to classify
            active_proposal: Active proposal dict with status='needs_confirmation'
                           or None if no active proposal exists

        Returns:
            RouterDecision with decision type, confidence, and reasoning

        Raises:
            LlmProviderCallError: On API call failures
            LlmProviderResponseError: On invalid/unparseable responses
        """
        logger.info(
            "routing_message",
            message_preview=user_message[:100],
            has_active_proposal=active_proposal is not None,
            provider=self.provider_name,
        )

        try:
            if self.provider_name == "openai":
                decision = await self._route_openai(user_message, active_proposal)
            elif self.provider_name == "gemini":
                decision = await self._route_gemini(user_message, active_proposal)
            else:
                # Fallback to safe default
                logger.warning("unknown_provider_fallback", provider=self.provider_name)
                return self._fallback_decision(user_message, active_proposal)

            logger.info(
                "routing_decision_made",
                decision=decision.decision.value,
                confidence=decision.confidence,
                reasoning=decision.reasoning[:100],
            )

            return decision

        except (LlmProviderCallError, LlmProviderResponseError) as e:
            logger.error(
                "routing_error_fallback",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fail-safe: return NEW_OPERATION so standard pipeline handles it
            return self._fallback_decision(user_message, active_proposal)

    async def _route_openai(
        self,
        user_message: str,
        active_proposal: dict[str, Any] | None,
    ) -> RouterDecision:
        """Route using OpenAI with structured output (parse method)."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)

            system_prompt = self._build_system_prompt(active_proposal)

            response = await client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format=RouterDecision,
                temperature=0.3,  # Lower temperature for routing decisions
            )

            parsed = response.choices[0].message.parsed
            if not parsed:
                raise LlmProviderResponseError(
                    "OpenAI returned empty parsed response",
                    details={"finish_reason": response.choices[0].finish_reason},
                )

            return parsed

        except ImportError:
            raise LlmProviderConfigError(
                "OpenAI library not installed. Install with: pip install openai",
                details={"provider": "openai"},
            )
        except Exception as e:
            logger.error("openai_routing_error", error=str(e))
            raise LlmProviderCallError(
                f"OpenAI routing failed: {e}",
                details={"error": str(e)},
            )

    async def _route_gemini(
        self,
        user_message: str,
        active_proposal: dict[str, Any] | None,
    ) -> RouterDecision:
        """Route using Gemini with JSON schema enforcement."""
        try:
            import google.generativeai as genai
            import json

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                self.model,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=RouterDecision,
                ),
            )

            system_prompt = self._build_system_prompt(active_proposal)
            full_prompt = f"{system_prompt}\n\nUser message: {user_message}"

            response = await model.generate_content_async(full_prompt)

            if not response.text:
                raise LlmProviderResponseError(
                    "Gemini returned empty response",
                    details={"model": self.model},
                )

            # Parse and validate
            response_data = json.loads(response.text)
            return RouterDecision(**response_data)

        except ImportError:
            raise LlmProviderConfigError(
                "Google Generative AI library not installed. "
                "Install with: pip install google-generativeai",
                details={"provider": "gemini"},
            )
        except ValidationError as e:
            logger.error("gemini_validation_error", error=str(e))
            raise LlmProviderResponseError(
                f"Gemini response validation failed: {e}",
                details={"errors": e.errors()},
            )
        except Exception as e:
            logger.error("gemini_routing_error", error=str(e))
            raise LlmProviderCallError(
                f"Gemini routing failed: {e}",
                details={"error": str(e)},
            )

    def _build_system_prompt(self, active_proposal: dict[str, Any] | None) -> str:
        """Build context-aware system prompt for routing."""
        available_tools_desc = """
        - create_task: Görev oluşturma
        - create_note: Not alma
        - get_weather: Hava durumu sorgulama
        - get_pharmacy_on_duty: Nöbetçi eczane sorgulama
        - get_exchange_rate: Döviz kuru sorgulama
        """
        base_prompt = """You are an Intent Router Agent. Your job is to classify user messages into categories.
1. CONFIRM_PROPOSAL - User is confirming/approving a proposal
   Turkish examples: "Onayla", "Onaylıyorum", "Tamam", "Evet", "Kabul", "Uygula", "Kaydet", "Yap", "Olur"
   English examples: "Approve", "Confirm", "Yes", "Accept", "Apply", "OK", "Okay", "Go ahead", "Do it"

2. REJECT_PROPOSAL - User is rejecting/canceling a proposal
   Turkish examples: "İptal", "Vazgeç", "İstemiyorum", "Hayır", "Geri al"
   English examples: "Cancel", "Nevermind", "No", "Discard", "Don't", "Reject", "Skip"

3. MODIFY_PROPOSAL - User wants to modify a proposal
   Turkish examples: "Saati 5 yap", "Hayır yarın olsun", "2 saat erken yap"
   English examples: "Change time to 5pm", "Make it tomorrow", "2 hours earlier"
   
4. CREATE_TASK_OR_NOTE - User wants to create/update tasks or notes explicitly.
   Ex: "Annemi ara", "Toplantı notu al", "Hatırlat", "Yarın dişçi"

5. TOOL_QUERY - User is asking for information that requires external tools (Weather, Pharmacy, FX, etc.)
   Ex: "Maltepe nöbetçi eczane", "Hava kaç derece?", "Dolar ne kadar?", "İstanbul'da yağmur var mı?"
   
6. CHITCHAT - User is engaging in casual conversation
   Turkish examples: "Selam", "Nasılsın", "Naber", "Teşekkürler"
   English examples: "Hello", "How are you", "Thanks", "Hi"
   
AVAILABLE TOOLS:
- Weather Forecast
- Pharmacy on Duty (Nöbetçi Eczane)
- Currency Exchange

CRITICAL RULES:
- You can ONLY return CONFIRM_PROPOSAL, REJECT_PROPOSAL, or MODIFY_PROPOSAL if there is an active proposal waiting for confirmation.
- If no active proposal exists, you MUST choose between NEW_OPERATION or CHITCHAT.
- For MODIFY_PROPOSAL, extract the user's modification request into suggested_modification field.
- Provide a confidence score (0.0 to 1.0) and brief reasoning.
- Pay special attention to Turkish keywords as the user may use Turkish language.
"""

        if active_proposal:
            # Build proposal context
            ops = active_proposal.get("ops", {})
            ops_list = ops.get("ops", [])
            reasoning = ops.get("reasoning", "")
            status = active_proposal.get("status", "unknown")

            ops_summary = self._summarize_ops(ops_list)

            context_prompt = f"""
ACTIVE PROPOSAL CONTEXT:
Status: {status}
Operations: {ops_summary}
Reasoning: {reasoning}

The user is likely responding to this proposal. Analyze if they are:
- Confirming it (CONFIRM_PROPOSAL)
- Rejecting it (REJECT_PROPOSAL)
- Requesting modifications (MODIFY_PROPOSAL)
- Or asking something completely different (NEW_OPERATION/CHITCHAT)
"""
        else:
            context_prompt = """
NO ACTIVE PROPOSAL:
There is no pending proposal. The user is either:
- Starting a new task/operation (NEW_OPERATION)
- Just chatting (CHITCHAT)

You CANNOT return CONFIRM_PROPOSAL, REJECT_PROPOSAL, or MODIFY_PROPOSAL.
"""

        return base_prompt + context_prompt

    def _summarize_ops(self, ops_list: list[dict[str, Any]]) -> str:
        """Summarize operations for context."""
        if not ops_list:
            return "No operations"

        summaries = []
        for op in ops_list[:3]:  # Show first 3 ops
            op_type = op.get("type", "unknown")
            title = op.get("title", "")
            summaries.append(f"{op_type}: {title}" if title else op_type)

        result = ", ".join(summaries)
        if len(ops_list) > 3:
            result += f" (and {len(ops_list) - 3} more)"

        return result

    def _fallback_decision(
        self,
        user_message: str,
        active_proposal: dict[str, Any] | None,
    ) -> RouterDecision:
        """
        Fail-safe fallback decision.

        When LLM fails, we default to NEW_OPERATION to ensure
        the standard pipeline handles the message safely.
        """
        logger.warning("using_fallback_decision")

        return RouterDecision(
            decision=RouterDecisionType.NEW_OPERATION,
            confidence=0.5,
            reasoning="Fallback decision due to routing error - defaulting to standard pipeline",
            suggested_modification=None,
        )
