"""OpenAI LLM provider implementation."""

import json
from datetime import datetime
from typing import Any

import httpx
import structlog
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam
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
from app.llm.intent_classifier import IntentType, classify_intent
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


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT provider.

    Requires OPENAI_API_KEY to be set. Raises LlmProviderConfigError if missing.
    
    Supports two modes:
    - Ops Mode: Traditional task/note management via JSON operations
    - Tool Mode: MCP-based tools (weather, FX) via Responses API
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_key = self.settings.OPENAI_API_KEY
        self.model = self.settings.OPENAI_MODEL
        self.timeout = self.settings.OPENAI_TIMEOUT
        self.mcp_server_url = self.settings.MCP_SERVER_URL
        self.mcp_enabled = self.settings.MCP_ENABLED

        # Validate configuration at initialization
        if not self.api_key:
            raise LlmProviderConfigError(
                "OPENAI_API_KEY is not configured. Set it in environment variables.",
                details={"provider": "openai", "setting": "OPENAI_API_KEY"},
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
        """Generate proposal using OpenAI API.

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
            client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )

            logger.info(
                "openai_request_start",
                model=self.model,
                message_count=len(messages_context),
            )

            response = await client.chat.completions.create(
                model=self.model,
                messages=prompt_messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                temperature=0.4,
            )

            content = response.choices[0].message.content
            if not content:
                raise LlmProviderResponseError(
                    "Empty response from OpenAI API",
                    details={
                        "model": self.model,
                        "finish_reason": response.choices[0].finish_reason,
                    },
                )

            logger.info(
                "openai_response_received",
                model=self.model,
                usage_tokens=response.usage.total_tokens if response.usage else None,
            )

            # Parse JSON response
            try:
                payload_data = json.loads(content)
            except json.JSONDecodeError as e:
                raise LlmProviderResponseError(
                    f"Invalid JSON in OpenAI response: {e}",
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

        except (APIConnectionError, APITimeoutError) as e:
            logger.error("openai_connection_error", error=str(e))
            raise LlmProviderCallError(
                f"Failed to connect to OpenAI API: {e}",
                details={"error_type": type(e).__name__},
            )

        except RateLimitError as e:
            logger.warning("openai_rate_limit", error=str(e))
            raise LlmProviderCallError(
                f"OpenAI rate limit exceeded: {e}",
                details={"error_type": "RateLimitError"},
            )

        except LlmProviderResponseError:
            # Re-raise response errors without wrapping
            raise

        except LlmProviderCallError:
            # Re-raise call errors without wrapping
            raise

        except ImportError:
            raise LlmProviderConfigError(
                "OpenAI library is not installed. Install with: pip install openai",
                details={"provider": "openai", "package": "openai"},
            )

        except Exception as e:
            # Catch any unexpected errors and wrap them
            logger.error(
                "openai_unexpected_error", error=str(e), error_type=type(e).__name__
            )
            raise LlmProviderCallError(
                f"Unexpected error calling OpenAI API: {e}",
                details={"error_type": type(e).__name__, "error": str(e)},
            )

    async def generate_tool_response(
        self,
        messages_context: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Generate response using MCP tools via OpenAI Responses API.
        
        This method enables the model to call external tools (weather, FX)
        dynamically via the MCP server without manually passing schemas.
        
        Args:
            messages_context: Recent conversation messages.
            
        Returns:
            Dictionary with:
                - text: Final response text
                - tool_calls: List of executed tool calls with results
                
        Raises:
            LlmProviderCallError: On API call failures.
            LlmProviderResponseError: On invalid/unparseable responses.
        """
        if not self.mcp_enabled:
            logger.warning("mcp_disabled", mcp_enabled=self.mcp_enabled)
            return {
                "text": "MCP tool mode is currently disabled. Please enable it in configuration.",
                "tool_calls": [],
            }
        
        # Test MCP server availability before making OpenAI call
        try:
            async with httpx.AsyncClient(timeout=5.0) as test_client:
                health_url = self.mcp_server_url.replace("/sse", "/health").replace("/mcp", "/health")
                health_response = await test_client.get(health_url)
                health_response.raise_for_status()
                logger.info("mcp_server_available", url=health_url)
        except Exception as e:
            logger.error("mcp_server_unavailable", error=str(e), url=self.mcp_server_url)
            return {
                "text": f"MCP tool server is currently unavailable. Please try again later. Error: {str(e)}",
                "tool_calls": [],
            }
        
        try:
            client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )

            logger.info(
                "openai_mcp_request_start",
                model=self.model,
                mcp_server_url=self.mcp_server_url,
                message_count=len(messages_context),
            )

            # Build MCP tool configuration per OpenAI docs
            mcp_tool_config = {
                "type": "mcp",
                "server_label": "notex-mcp",
                "server_description": "Weather, FX conversion, on-duty pharmacy tools",
                "server_url": self.mcp_server_url,
                "require_approval": "never",
            }

            # Get the last user message as input (Responses API uses single input, not messages array)
            last_user_message = next(
                (msg["content"] for msg in reversed(messages_context) if msg["role"] == "user"),
                "What can you help me with?"
            )

            # Call Responses API with MCP tools
            response = await client.responses.create(
                model=self.model,
                input=last_user_message,  # Responses API uses 'input' not 'messages'
                tools=[mcp_tool_config],  # type: ignore[arg-type]
                temperature=0.7,
            )

            logger.info(
                "openai_mcp_response_received",
                model=self.model,
                usage_tokens=response.usage.total_tokens if response.usage else None,
            )

            # Parse output items (mcp_list_tools, mcp_call, output_text)
            tool_calls = []
            final_text = ""
            
            for output_item in response.output:
                item_type = getattr(output_item, 'type', None)
                
                if item_type == "mcp_list_tools":
                    # Tool discovery phase - tools are Pydantic objects
                    tools = getattr(output_item, 'tools', [])
                    tool_count = len(tools) if tools else 0
                    # Access tool names via attribute (Pydantic) or dict key
                    tool_names = []
                    for t in (tools or []):
                        if hasattr(t, 'name'):
                            tool_names.append(t.name)
                        elif isinstance(t, dict):
                            tool_names.append(t.get('name'))
                    logger.info("mcp_tools_discovered", tool_count=tool_count, tools=tool_names)
                    
                elif item_type == "mcp_call":
                    # Tool execution
                    tool_name = getattr(output_item, 'name', None)
                    tool_args = getattr(output_item, 'arguments', {})
                    tool_output = getattr(output_item, 'output', None)
                    tool_error = getattr(output_item, 'error', None)
                    
                    logger.info(
                        "mcp_tool_executed",
                        tool=tool_name,
                        args=tool_args,
                        output=tool_output,
                        error=tool_error,
                    )
                    
                    tool_calls.append({
                        "name": tool_name,
                        "arguments": tool_args,
                        "output": tool_output,
                        "error": tool_error,
                    })
                    
                elif item_type == "message":
                    # Final model response (message type contains content)
                    content = getattr(output_item, 'content', [])
                    for content_item in content:
                        if getattr(content_item, 'type', None) == 'output_text':
                            final_text = getattr(content_item, 'text', "")
                            logger.info("mcp_output_text_received", text_length=len(final_text))
            
            if not final_text and not tool_calls:
                logger.warning("mcp_empty_response")
                final_text = "No response generated from MCP tools."
            
            return {
                "text": final_text,
                "tool_calls": tool_calls,
            }

        except (APIConnectionError, APITimeoutError) as e:
            logger.error("openai_mcp_connection_error", error=str(e))
            raise LlmProviderCallError(
                f"Failed to connect to OpenAI API for MCP tools: {e}",
                details={"error_type": type(e).__name__},
            )

        except RateLimitError as e:
            logger.warning("openai_mcp_rate_limit", error=str(e))
            raise LlmProviderCallError(
                f"OpenAI rate limit exceeded: {e}",
                details={"error_type": "RateLimitError"},
            )

        except ImportError:
            raise LlmProviderConfigError(
                "OpenAI library is not installed. Install with: pip install openai",
                details={"provider": "openai", "package": "openai"},
            )

        except Exception as e:
            logger.error(
                "openai_mcp_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise LlmProviderCallError(
                f"Unexpected error calling OpenAI MCP API: {e}",
                details={"error_type": type(e).__name__, "error": str(e)},
            )

