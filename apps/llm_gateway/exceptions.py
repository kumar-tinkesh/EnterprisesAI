"""
LLM Gateway — Custom exception hierarchy.
"""

from __future__ import annotations

from typing import Optional


class LLMGatewayError(Exception):
    """Base exception for all gateway errors."""

    def __init__(
        self,
        message: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


class ProviderNotConfiguredError(LLMGatewayError):
    """Raised when a provider's API key is missing or empty."""


class ProviderAPIError(LLMGatewayError):
    """Raised when the upstream provider returns an error response."""


class RateLimitError(ProviderAPIError):
    """Raised on HTTP 429 — the caller should back off or failover."""

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, retryable=True, **kwargs)


class AuthenticationError(ProviderAPIError):
    """Raised on HTTP 401 / 403 — invalid or revoked API key."""


class ModelNotFoundError(ProviderAPIError):
    """Raised when the requested model does not exist on the provider."""


class TokenLimitExceededError(ProviderAPIError):
    """Raised when the request exceeds the model's context window."""


class ContentFilterError(ProviderAPIError):
    """Raised when content is blocked by the provider's safety filters."""
