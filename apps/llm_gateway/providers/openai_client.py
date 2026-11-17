"""
LLM Gateway — OpenAI provider client.

A thin subclass of :class:`LiteLLMClient` that routes to OpenAI through
LiteLLM using the ``openai/`` model-string prefix. All HTTP work, error
mapping and response normalisation live in :class:`LiteLLMClient`; this class
only declares the provider identity, defaults and the model prefix.

The class name (``OpenAIClient``) is kept identical so the gateway factory and
existing tests that patch ``apps.llm_gateway.gateway.OpenAIClient`` keep
working unchanged.
"""

from __future__ import annotations

from apps.llm_gateway.providers.litellm_client import LiteLLMClient


class OpenAIClient(LiteLLMClient):
    """Async client for OpenAI (and OpenAI-compatible) endpoints via LiteLLM."""

    PROVIDER_NAME = "openai"
    _PREFIX = "openai/"
    _DEFAULT_EMBED_MODEL = "text-embedding-3-small"
    EMBEDDINGS_SUPPORTED = True
    # OpenAI base_url may be a custom proxy — forward it when set.
    _PASS_API_BASE = True