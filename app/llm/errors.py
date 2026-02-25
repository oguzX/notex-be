"""LLM provider error types.

These exceptions are raised by LLM providers and caught by the worker
to set appropriate proposal status and error information.
"""


class LlmError(Exception):
    """Base exception for all LLM-related errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LlmProviderConfigError(LlmError):
    """Raised when LLM provider is misconfigured (e.g., missing API key).

    Worker should set proposal.status='failed' with error_code='LLM_CONFIG'.
    """

    error_code = "LLM_CONFIG"


class LlmProviderCallError(LlmError):
    """Raised when the API call to the LLM provider fails.

    This includes network errors, timeouts, rate limits, etc.
    Worker should set proposal.status='failed' with error_code='LLM_CALL'.
    """

    error_code = "LLM_CALL"


class LlmProviderResponseError(LlmError):
    """Raised when the LLM returns an invalid or unparseable response.

    This includes non-JSON responses, schema validation failures, etc.
    Worker should set proposal.status='failed' with error_code='LLM_RESPONSE'.
    """

    error_code = "LLM_RESPONSE"
