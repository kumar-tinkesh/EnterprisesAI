"""
LLM Gateway — Google Gemini provider client.

A thin subclass of :class:`LiteLLMClient` that routes to Gemini through
LiteLLM using the ``gemini/`` model-string prefix. LiteLLM talks to Gemini's
*native* API (not the OpenAI-compatible gateway), so ``_PASS_API_BASE`` is
``False`` — the configured ``GEMINI_BASE_URL`` (an OpenAI-compat path) is
intentionally not forwarded, avoiding a conflict with LiteLLM's native
routing. Embeddings are supported (``gemini-embedding-001``).

The class name (``GeminiClient``) is kept identical so the gateway factory and
existing tests that patch ``apps.llm_gateway.gateway.GeminiClient`` keep
working unchanged.
"""

from __future__ import annotations

from apps.llm_gateway.providers.litellm_client import LiteLLMClient


class GeminiClient(LiteLLMClient):
    """Async client for Google Gemini via LiteLLM's native Gemini routing."""

    PROVIDER_NAME = "gemini"
    _PREFIX = "gemini/"
    _DEFAULT_EMBED_MODEL = "gemini-embedding-001"
    EMBEDDINGS_SUPPORTED = True
    # Do NOT forward the OpenAI-compat base_url — LiteLLM routes natively.
    _PASS_API_BASE = False