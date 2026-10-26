"""
LLM Gateway — Azure OpenAI provider client.

Its own provider (``azure``), configured from the ``AZURE_OPENAI_*`` variables,
so it can sit next to a plain OpenAI key. Azure routes by *deployment name*:
the configured deployment is used for every call (set once, like a key), and
``ProviderConfig.force_azure`` makes :class:`LiteLLMClient` add the
``azure/`` prefix and ``api_version``.
"""

from __future__ import annotations

from typing import Optional

from apps.llm_gateway.config import ProviderConfig
from apps.llm_gateway.exceptions import ProviderNotConfiguredError
from apps.llm_gateway.providers.openai_client import OpenAIClient
from apps.llm_gateway.types import EmbeddingResponse


class AzureOpenAIClient(OpenAIClient):
    """Async client for Azure OpenAI deployments via LiteLLM."""

    PROVIDER_NAME = "azure"
    _PREFIX = "azure/"

    def __init__(self, config: ProviderConfig) -> None:
        if not config.is_configured:
            raise ProviderNotConfiguredError(
                "Azure OpenAI isn't configured: set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT.",
                provider=self.PROVIDER_NAME,
            )
        super().__init__(config)

    async def embed(self, texts: list[str], *, model: Optional[str] = None) -> EmbeddingResponse:
        # Without an embedding deployment every call would 404 (after retries):
        # say so at once, so the gateway moves on to the next provider.
        if not self._config.azure_embedding_deployment and not (model and "/" in model):
            raise ProviderNotConfiguredError(
                "Azure OpenAI has no embedding deployment: set AZURE_OPENAI_EMBEDDING_DEPLOYMENT.",
                provider=self.PROVIDER_NAME,
            )
        return await super().embed(texts, model=model)
