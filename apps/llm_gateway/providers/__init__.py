"""
LLM Gateway — Providers sub-package.

All providers are backed by LiteLLM (see :class:`LiteLLMClient`). The concrete
classes are thin subclasses that declare provider identity, model-string
prefix and defaults. Re-exported here for convenience.
"""

from apps.llm_gateway.providers.base import BaseLLMClient
from apps.llm_gateway.providers.litellm_client import LiteLLMClient
from apps.llm_gateway.providers.openai_client import OpenAIClient
from apps.llm_gateway.providers.groq_client import GroqClient
from apps.llm_gateway.providers.gemini_client import GeminiClient

__all__ = [
    "BaseLLMClient",
    "LiteLLMClient",
    "OpenAIClient",
    "GroqClient",
    "GeminiClient",
]