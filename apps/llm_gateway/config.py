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
    """Credentials & defaults for a single LLM provider."""

    api_key: str = ""
    base_url: Optional[str] = None
    default_model: str = ""
    max_retries: int = 3
    timeout_seconds: int = 60
    organization: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class GatewaySettings:
    """
    Central gateway configuration assembled from environment variables.

    Environment variables consumed
    ──────────────────────────────
    OPENAI_API_KEY, OPENAI_ORG_ID, OPENAI_BASE_URL, OPENAI_DEFAULT_MODEL
    GROQ_API_KEY, GROQ_BASE_URL, GROQ_DEFAULT_MODEL
    GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_DEFAULT_MODEL
    LLM_GATEWAY_DEFAULT_PROVIDER   (openai | groq | gemini)
    LLM_GATEWAY_TIMEOUT            seconds, applies to all providers
    LLM_GATEWAY_MAX_RETRIES        retry count, applies to all providers
    LLM_GATEWAY_ENABLE_CACHE       1 | true | yes → enable response cache
    LLM_GATEWAY_CACHE_TTL          seconds (default 3600)
    """

    openai: ProviderConfig = field(default_factory=ProviderConfig)
    groq: ProviderConfig = field(default_factory=ProviderConfig)
    gemini: ProviderConfig = field(default_factory=ProviderConfig)
    default_provider: str = "openai"
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
            organization=os.getenv("OPENAI_ORG_ID"),
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

        return cls(
            openai=openai_cfg,
            groq=groq_cfg,
            gemini=gemini_cfg,
            default_provider=os.getenv("LLM_GATEWAY_DEFAULT_PROVIDER", "openai"),
            enable_cache=enable_cache,
            cache_ttl_seconds=cache_ttl,
        )
