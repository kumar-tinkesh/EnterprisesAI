"""
LLM Gateway — Groq provider client.

A thin subclass of :class:`LiteLLMClient` that routes to Groq through LiteLLM
using the ``groq/`` model-string prefix. Groq does not serve embeddings, so
``EMBEDDINGS_SUPPORTED`` is ``False`` and the base ``embed`` raises.

The class name (``GroqClient``) is kept identical so the gateway factory and
existing tests that patch ``apps.llm_gateway.gateway.GroqClient`` keep working
unchanged.
"""

from __future__ import annotations

from apps.llm_gateway.providers.litellm_client import LiteLLMClient


class GroqClient(LiteLLMClient):
    """Async client for Groq (ultra-low-latency inference) via LiteLLM."""

    PROVIDER_NAME = "groq"
    _PREFIX = "groq/"
    _DEFAULT_EMBED_MODEL = ""
    EMBEDDINGS_SUPPORTED = False
    _PASS_API_BASE = True