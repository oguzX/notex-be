"""Tests for LLM provider error handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.llm.errors import (
    LlmError,
    LlmProviderCallError,
    LlmProviderConfigError,
    LlmProviderResponseError,
)
from app.llm.factory import get_llm_provider


class TestLlmErrors:
    """Test LLM error classes."""

    def test_llm_error_base(self):
        """Test base LlmError."""
        error = LlmError("Test error", details={"key": "value"})
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.details == {"key": "value"}

    def test_llm_error_default_details(self):
        """Test LlmError with default empty details."""
        error = LlmError("Test error")
        assert error.details == {}

    def test_llm_provider_config_error(self):
        """Test LlmProviderConfigError."""
        error = LlmProviderConfigError(
            "API key missing",
            details={"provider": "openai"},
        )
        assert error.error_code == "LLM_CONFIG"
        assert error.message == "API key missing"
        assert error.details == {"provider": "openai"}

    def test_llm_provider_call_error(self):
        """Test LlmProviderCallError."""
        error = LlmProviderCallError(
            "Connection timeout",
            details={"timeout": 30},
        )
        assert error.error_code == "LLM_CALL"
        assert error.message == "Connection timeout"

    def test_llm_provider_response_error(self):
        """Test LlmProviderResponseError."""
        error = LlmProviderResponseError(
            "Invalid JSON response",
            details={"raw_content": "not json"},
        )
        assert error.error_code == "LLM_RESPONSE"
        assert error.message == "Invalid JSON response"


class TestLlmFactory:
    """Test LLM factory error handling."""

    def test_unknown_provider_raises_config_error(self):
        """Test that unknown provider raises LlmProviderConfigError."""
        with patch("app.llm.factory.get_settings") as mock_settings:
            mock_settings.return_value.LLM_PROVIDER = "unknown_provider"
            
            with pytest.raises(LlmProviderConfigError) as exc_info:
                get_llm_provider()
            
            assert "Unknown LLM provider" in str(exc_info.value)
            assert exc_info.value.error_code == "LLM_CONFIG"

    def test_openai_missing_api_key_raises_config_error(self):
        """Test that OpenAI provider with missing API key raises LlmProviderConfigError."""
        with patch("app.llm.factory.get_settings") as mock_factory_settings, \
             patch("app.llm.openai_provider.get_settings") as mock_provider_settings:
            mock_factory_settings.return_value.LLM_PROVIDER = "openai"
            mock_provider_settings.return_value.OPENAI_API_KEY = None
            mock_provider_settings.return_value.OPENAI_MODEL = "gpt-4"
            mock_provider_settings.return_value.OPENAI_TIMEOUT = 30
            
            with pytest.raises(LlmProviderConfigError) as exc_info:
                get_llm_provider()
            
            assert "OPENAI_API_KEY" in str(exc_info.value)
            assert exc_info.value.error_code == "LLM_CONFIG"

    def test_gemini_missing_api_key_raises_config_error(self):
        """Test that Gemini provider with missing API key raises LlmProviderConfigError."""
        with patch("app.llm.factory.get_settings") as mock_factory_settings, \
             patch("app.llm.gemini_provider.get_settings") as mock_provider_settings:
            mock_factory_settings.return_value.LLM_PROVIDER = "gemini"
            mock_provider_settings.return_value.GEMINI_API_KEY = None
            mock_provider_settings.return_value.GEMINI_MODEL = "gemini-pro"
            mock_provider_settings.return_value.GEMINI_TIMEOUT = 30
            
            with pytest.raises(LlmProviderConfigError) as exc_info:
                get_llm_provider()
            
            assert "GEMINI_API_KEY" in str(exc_info.value)
            assert exc_info.value.error_code == "LLM_CONFIG"


class TestOpenAIProviderErrors:
    """Test OpenAI provider error scenarios."""

    @pytest.mark.asyncio
    async def test_api_connection_error_raises_call_error(self):
        """Test that API connection errors are wrapped in LlmProviderCallError."""
        from app.llm.openai_provider import OpenAIProvider
        
        with patch("app.llm.openai_provider.get_settings") as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = "test-key"
            mock_settings.return_value.OPENAI_MODEL = "gpt-4"
            mock_settings.return_value.OPENAI_TIMEOUT = 30
            
            provider = OpenAIProvider()
            
            # Mock the OpenAI client inside the method
            with patch("openai.AsyncOpenAI") as mock_client:
                from openai import APIConnectionError
                
                mock_instance = AsyncMock()
                mock_instance.chat.completions.create = AsyncMock(
                    side_effect=APIConnectionError(request=MagicMock())
                )
                mock_client.return_value = mock_instance
                
                with pytest.raises(LlmProviderCallError) as exc_info:
                    await provider.generate_proposal(
                        messages_context=[{"role": "user", "content": "Hello"}],
                        tasks_snapshot=[],
                        timezone="UTC",
                    )
                
                assert exc_info.value.error_code == "LLM_CALL"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_response_error(self):
        """Test that invalid JSON response raises LlmProviderResponseError."""
        from app.llm.openai_provider import OpenAIProvider
        
        with patch("app.llm.openai_provider.get_settings") as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = "test-key"
            mock_settings.return_value.OPENAI_MODEL = "gpt-4"
            mock_settings.return_value.OPENAI_TIMEOUT = 30
            
            provider = OpenAIProvider()
            
            # Mock the OpenAI client to return invalid JSON
            with patch("openai.AsyncOpenAI") as mock_client:
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = "not valid json {"
                mock_response.choices[0].finish_reason = "stop"
                mock_response.usage = MagicMock(total_tokens=100)
                
                mock_instance = AsyncMock()
                mock_instance.chat.completions.create = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_instance
                
                with pytest.raises(LlmProviderResponseError) as exc_info:
                    await provider.generate_proposal(
                        messages_context=[{"role": "user", "content": "Hello"}],
                        tasks_snapshot=[],
                        timezone="UTC",
                    )
                
                assert exc_info.value.error_code == "LLM_RESPONSE"
                assert "Invalid JSON" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_schema_validation_error_raises_response_error(self):
        """Test that schema validation errors raise LlmProviderResponseError."""
        from app.llm.openai_provider import OpenAIProvider
        
        with patch("app.llm.openai_provider.get_settings") as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = "test-key"
            mock_settings.return_value.OPENAI_MODEL = "gpt-4"
            mock_settings.return_value.OPENAI_TIMEOUT = 30
            
            provider = OpenAIProvider()
            
            # Mock the OpenAI client to return invalid schema
            with patch("openai.AsyncOpenAI") as mock_client:
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                # Valid JSON but missing required fields
                mock_response.choices[0].message.content = '{"invalid_field": true}'
                mock_response.choices[0].finish_reason = "stop"
                mock_response.usage = MagicMock(total_tokens=100)
                
                mock_instance = AsyncMock()
                mock_instance.chat.completions.create = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_instance
                
                with pytest.raises(LlmProviderResponseError) as exc_info:
                    await provider.generate_proposal(
                        messages_context=[{"role": "user", "content": "Hello"}],
                        tasks_snapshot=[],
                        timezone="UTC",
                    )
                
                assert exc_info.value.error_code == "LLM_RESPONSE"
                assert "schema" in str(exc_info.value).lower()
