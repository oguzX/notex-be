"""LLM provider factory."""

import structlog

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider
from app.llm.errors import LlmProviderConfigError

logger = structlog.get_logger(__name__)


def get_llm_provider() -> BaseLLMProvider:
    """Get LLM provider based on configuration.

    Returns the appropriate provider instance based on LLM_PROVIDER setting.
    Provider initialization validates configuration and raises LlmProviderConfigError
    if the provider is misconfigured (e.g., missing API key).

    Raises:
        LlmProviderConfigError: If the selected provider is misconfigured or unknown.
    """
    settings = get_settings()
    provider_name = settings.LLM_PROVIDER

    if provider_name == "openai":
        from app.llm.openai_provider import OpenAIProvider

        logger.info("using_openai_provider")
        return OpenAIProvider()

    elif provider_name == "gemini":
        from app.llm.gemini_provider import GeminiProvider

        logger.info("using_gemini_provider")
        return GeminiProvider()

    else:
        raise LlmProviderConfigError(
            f"Unknown LLM provider: {provider_name}. "
            "Supported providers: 'openai', 'gemini'.",
            details={"provider": provider_name, "supported": ["openai", "gemini"]},
        )
