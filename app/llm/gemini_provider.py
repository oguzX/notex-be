"""Google Gemini LLM provider implementation."""

import json
from datetime import datetime
from typing import Any

import structlog
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider
from app.llm.errors import (
    LlmProviderCallError,
    LlmProviderConfigError,
    LlmProviderResponseError,
)
from app.llm.prompts import build_prompt
from app.schemas.proposals import LlmProposalPayload
from app.utils.ids import generate_clarification_id

logger = structlog.get_logger(__name__)


def _normalize_clarifications(payload_data: dict) -> dict:
    """Ensure every clarification has a clarification_id.
    
    LLMs may omit clarification_id. This function adds server-generated IDs
    for any clarification missing the field, preventing validation failures.
    """
    clarifications = payload_data.get("clarifications", [])
    if isinstance(clarifications, list):
        for clarification in clarifications:
            if isinstance(clarification, dict) and not clarification.get("clarification_id"):
                clarification["clarification_id"] = generate_clarification_id()
    return payload_data

# Retry configuration: 2 retries with exponential backoff (1s, 2s)
RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 1
RETRY_MAX_WAIT = 4


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider.

    Requires GEMINI_API_KEY to be set. Raises LlmProviderConfigError if missing.
    All API calls use the official Google Generative AI SDK with JSON response format.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.model = self.settings.GEMINI_MODEL
        self.timeout = self.settings.GEMINI_TIMEOUT

        # Validate configuration at initialization
        if not self.api_key:
            raise LlmProviderConfigError(
                "GEMINI_API_KEY is not configured. Set it in environment variables.",
                details={"provider": "gemini", "setting": "GEMINI_API_KEY"},
            )

    @retry(
        retry=retry_if_exception_type(LlmProviderCallError),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
        reraise=True,
    )
    async def generate_proposal(
        self,
        messages_context: list[dict[str, str]],
        tasks_snapshot: list[dict[str, Any]],
        timezone: str = "UTC",
        auto_apply: bool = True,
        reference_dt_utc: datetime | None = None,
    ) -> LlmProposalPayload:
        """Generate proposal using Gemini API.

        Args:
            messages_context: Recent conversation messages.
            tasks_snapshot: Current task state for context.
            timezone: User's timezone.
            auto_apply: Whether to auto-apply proposals.
            reference_dt_utc: Reference datetime for relative date parsing.

        Returns:
            LlmProposalPayload with task operations.

        Raises:
            LlmProviderCallError: On API call failures (network, timeout, rate limit).
            LlmProviderResponseError: On invalid/unparseable responses.
        """
        prompt_messages = build_prompt(
            messages_context,
            tasks_snapshot,
            timezone,
            auto_apply,
            reference_dt_utc=reference_dt_utc,
        )

        try:
            import google.generativeai as genai
            from google.api_core import exceptions as google_exceptions

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model)

            # Convert messages to Gemini format
            full_prompt = "\n\n".join(
                [f"{msg['role']}: {msg['content']}" for msg in prompt_messages]
            )

            logger.info(
                "gemini_request_start",
                model=self.model,
                message_count=len(messages_context),
            )

            response = await model.generate_content_async(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    response_mime_type="application/json",
                ),
                request_options={"timeout": self.timeout},
            )

            content = response.text
            if not content:
                raise LlmProviderResponseError(
                    "Empty response from Gemini API",
                    details={"model": self.model},
                )

            logger.info(
                "gemini_response_received",
                model=self.model,
            )

            # Parse JSON response
            try:
                payload_data = json.loads(content)
            except json.JSONDecodeError as e:
                raise LlmProviderResponseError(
                    f"Invalid JSON in Gemini response: {e}",
                    details={"raw_content": content[:500], "error": str(e)},
                )

            # Normalize clarifications (add missing clarification_id)
            payload_data = _normalize_clarifications(payload_data)

            # Validate against Pydantic schema
            try:
                return LlmProposalPayload(**payload_data)
            except ValidationError as e:
                raise LlmProviderResponseError(
                    f"Response does not match expected schema: {e}",
                    details={"payload": payload_data, "validation_errors": e.errors()},
                )

        except google_exceptions.DeadlineExceeded as e:
            logger.error("gemini_timeout", error=str(e))
            raise LlmProviderCallError(
                f"Gemini API request timed out: {e}",
                details={"error_type": "DeadlineExceeded"},
            )

        except google_exceptions.ResourceExhausted as e:
            logger.warning("gemini_rate_limit", error=str(e))
            raise LlmProviderCallError(
                f"Gemini rate limit exceeded: {e}",
                details={"error_type": "ResourceExhausted"},
            )

        except google_exceptions.GoogleAPIError as e:
            logger.error("gemini_api_error", error=str(e))
            raise LlmProviderCallError(
                f"Gemini API error: {e}",
                details={"error_type": type(e).__name__},
            )

        except LlmProviderResponseError:
            # Re-raise response errors without wrapping
            raise

        except LlmProviderCallError:
            # Re-raise call errors without wrapping
            raise

        except ImportError:
            raise LlmProviderConfigError(
                "Google Generative AI library is not installed. "
                "Install with: pip install google-generativeai",
                details={"provider": "gemini", "package": "google-generativeai"},
            )

        except Exception as e:
            # Catch any unexpected errors and wrap them
            logger.error(
                "gemini_unexpected_error", error=str(e), error_type=type(e).__name__
            )
            raise LlmProviderCallError(
                f"Unexpected error calling Gemini API: {e}",
                details={"error_type": type(e).__name__, "error": str(e)},
            )
