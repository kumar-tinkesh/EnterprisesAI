"""
LLM Gateway — Configuration & Settings
Loads provider API keys and gateway defaults from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProviderConfig:
    """Credentials & defaults for a single LLM provider.

    ``azure_chat_deployment``/``azure_embedding_deployment`` only apply to
    the ``openai`` provider config when it's actually pointed at Azure
    OpenAI (see :attr:`is_azure`) — Azure routes by *deployment name*, which
    may differ from the underlying model name, instead of by model name.
    """

    api_key: str = ""
    base_url: Optional[str] = None
    default_model: str = ""
    max_retries: int = 3
    timeout_seconds: int = 60
    organization: Optional[str] = None
    api_version: Optional[str] = None
    default_embedding_model: str = ""
    azure_chat_deployment: str = ""
    azure_embedding_deployment: str = ""
    # The dedicated ``azure`` provider: always Azure routing, whatever the
    # endpoint's host (custom domains included).
    force_azure: bool = False

    @property
    def is_configured(self) -> bool:
        if self.force_azure:
            return bool(self.api_key and self.base_url)
        return bool(self.api_key)

    @property
    def is_azure(self) -> bool:
        """True when ``base_url`` is an Azure OpenAI endpoint (``*.azure.com``)
        with an ``api_version`` set — Azure OpenAI requires both a
        deployment-scoped URL and an ``api-version`` query param, unlike
        plain OpenAI-compatible endpoints."""
        if self.force_azure:
            return True
        return bool(
            self.base_url
            and "azure.com" in self.base_url.lower()
            and self.api_version
        )


@dataclass(frozen=True)
class GatewaySettings:
    """
    Central gateway configuration assembled from environment variables.

    Environment variables consumed
    ──────────────────────────────
    OPENAI_API_KEY, OPENAI_ORG_ID, OPENAI_BASE_URL, OPENAI_DEFAULT_MODEL
    OPENAI_API_VERSION             Azure OpenAI only — enables Azure routing
                                    when OPENAI_BASE_URL is a *.azure.com URL
    AZURE_OPENAI_CHAT_DEPLOYMENT       optional — defaults to OPENAI_DEFAULT_MODEL
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT  optional — defaults to OPENAI_EMBEDDING_MODEL
    AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT   the dedicated ``azure`` provider
    AZURE_OPENAI_API_VERSION       default 2024-06-01
    AZURE_OPENAI_DEPLOYMENT        chat deployment name (default gpt-4o-mini)
                                    AZURE_OPENAI_EMBEDDING_DEPLOYMENT doubles as
                                    its embedding deployment
    GROQ_API_KEY, GROQ_BASE_URL, GROQ_DEFAULT_MODEL
    GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_DEFAULT_MODEL
    LLM_GATEWAY_DEFAULT_PROVIDER   (azure | openai | groq | gemini) — when unset,
                                    azure if it's configured, else openai
    LLM_GATEWAY_EMBEDDING_PROVIDER when unset, azure if it has an embedding
                                    deployment, else gemini
    LLM_GATEWAY_TIMEOUT            seconds, applies to all providers
    LLM_GATEWAY_MAX_RETRIES        retry count, applies to all providers
    LLM_GATEWAY_ENABLE_CACHE       1 | true | yes → enable response cache
    LLM_GATEWAY_CACHE_TTL          seconds (default 3600)
    """

    openai: ProviderConfig = field(default_factory=ProviderConfig)
    groq: ProviderConfig = field(default_factory=ProviderConfig)
    gemini: ProviderConfig = field(default_factory=ProviderConfig)
    azure: ProviderConfig = field(default_factory=ProviderConfig)
    default_provider: str = "openai"
    embedding_provider: str = "gemini"
    enable_cache: bool = False
    cache_ttl_seconds: int = 3600

    @classmethod
    def from_env(cls) -> GatewaySettings:
        """Build settings by reading os.environ (or a pre-loaded .env)."""
        try:
            from dotenv import find_dotenv, load_dotenv
            load_dotenv(find_dotenv(usecwd=True), override=False)
        except ImportError:
            pass

        timeout = int(os.getenv("LLM_GATEWAY_TIMEOUT", "60"))
        retries = int(os.getenv("LLM_GATEWAY_MAX_RETRIES", "3"))
        enable_cache = os.getenv("LLM_GATEWAY_ENABLE_CACHE", "").lower() in (
            "1",
            "true",
            "yes",
        )
        cache_ttl = int(os.getenv("LLM_GATEWAY_CACHE_TTL", "3600"))

        openai_cfg = ProviderConfig(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL"),
            default_model=os.getenv("OPENAI_DEFAULT_MODEL", ""),
            default_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", ""),
            organization=os.getenv("OPENAI_ORG_ID"),
            api_version=os.getenv("OPENAI_API_VERSION"),
            azure_chat_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", ""),
            azure_embedding_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""),
            max_retries=retries,
            timeout_seconds=timeout,
        )

        groq_cfg = ProviderConfig(
            api_key=os.getenv("GROQ_API_KEY", ""),
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            default_model=os.getenv("GROQ_DEFAULT_MODEL", ""),
            max_retries=retries,
            timeout_seconds=timeout,
        )

        gemini_cfg = ProviderConfig(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            base_url=os.getenv(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            default_model=os.getenv("GEMINI_DEFAULT_MODEL", ""),
            max_retries=retries,
            timeout_seconds=timeout,
        )

        azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "") or "gpt-4o-mini"
        azure_embedding = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
        azure_cfg = ProviderConfig(
            api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            base_url=os.getenv("AZURE_OPENAI_ENDPOINT") or None,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "") or "2024-06-01",
            default_model=azure_deployment,
            azure_chat_deployment=azure_deployment,
            default_embedding_model=azure_embedding,
            azure_embedding_deployment=azure_embedding,
            force_azure=True,
            max_retries=retries,
            timeout_seconds=timeout,
        )

        # Empty counts as unset (docker compose passes "" for unset vars).
        default_provider = os.getenv("LLM_GATEWAY_DEFAULT_PROVIDER", "").strip().lower() or (
            "azure" if azure_cfg.is_configured else "openai"
        )
        embedding_provider = os.getenv("LLM_GATEWAY_EMBEDDING_PROVIDER", "").strip().lower() or (
            "azure" if azure_cfg.is_configured and azure_embedding else "gemini"
        )

        return cls(
            openai=openai_cfg,
            groq=groq_cfg,
            gemini=gemini_cfg,
            azure=azure_cfg,
            default_provider=default_provider,
            embedding_provider=embedding_provider,
            enable_cache=enable_cache,
            cache_ttl_seconds=cache_ttl,
        )
