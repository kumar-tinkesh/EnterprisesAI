"""
LLM Gateway — Unified Prompt Registry & Template Manager.

Provides type-safe prompt retrieval, variable interpolation, and provider-specific
overrides for agentic workflows across the platform.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from apps.llm_gateway.prompts.templates import (
    SYSTEM_AI_DESIGNER,
    SYSTEM_GRAPH_PATCHER,
    SYSTEM_REACT_AGENT,
    SYSTEM_RAG_QUERY_REWRITE,
    SYSTEM_RAG_GROUNDED_QA,
    SYSTEM_GUARDRAIL_INSPECTOR,
    SYSTEM_EVALUATION_JUDGE,
    SYSTEM_DOCUMENT_EXTRACTION,
)


class PromptType(str, Enum):
    """Enumeration of all supported agentic prompt templates."""

    AI_DESIGNER = "ai_designer"
    GRAPH_PATCHER = "graph_patcher"
    REACT_AGENT = "react_agent"
    RAG_QUERY_REWRITE = "rag_query_rewrite"
    RAG_GROUNDED_QA = "rag_grounded_qa"
    GUARDRAIL_INSPECTOR = "guardrail_inspector"
    EVALUATION_JUDGE = "evaluation_judge"
    DOCUMENT_EXTRACTION = "document_extraction"


class PromptRegistry:
    """
    Central registry for managing, formatting, and rendering system prompts.

    Usage
    ─────
    ```python
    from apps.llm_gateway.prompts import PromptRegistry, PromptType

    # Render a ReAct Agent system prompt
    prompt = PromptRegistry.format(
        PromptType.REACT_AGENT,
        agent_goal="Onboard new employee John Doe",
        bound_tools=["hris.createEmployee", "slack.sendMessage"],
        knowledge_context="HR Policy v2.1",
        memory_context="No previous runs",
    )
    ```
    """

    _TEMPLATES: dict[PromptType, str] = {
        PromptType.AI_DESIGNER: SYSTEM_AI_DESIGNER,
        PromptType.GRAPH_PATCHER: SYSTEM_GRAPH_PATCHER,
        PromptType.REACT_AGENT: SYSTEM_REACT_AGENT,
        PromptType.RAG_QUERY_REWRITE: SYSTEM_RAG_QUERY_REWRITE,
        PromptType.RAG_GROUNDED_QA: SYSTEM_RAG_GROUNDED_QA,
        PromptType.GUARDRAIL_INSPECTOR: SYSTEM_GUARDRAIL_INSPECTOR,
        PromptType.EVALUATION_JUDGE: SYSTEM_EVALUATION_JUDGE,
        PromptType.DOCUMENT_EXTRACTION: SYSTEM_DOCUMENT_EXTRACTION,
    }

    _CUSTOM_OVERRIDES: dict[str, dict[PromptType, str]] = {}

    @classmethod
    def get_template(
        cls, prompt_type: PromptType, provider: Optional[str] = None
    ) -> str:
        """
        Retrieve raw prompt template string, applying provider-specific overrides if set.
        """
        if provider and provider in cls._CUSTOM_OVERRIDES:
            if prompt_type in cls._CUSTOM_OVERRIDES[provider]:
                return cls._CUSTOM_OVERRIDES[provider][prompt_type]

        template = cls._TEMPLATES.get(prompt_type)
        if not template:
            raise KeyError(f"Prompt type '{prompt_type}' not found in registry.")
        return template

    @classmethod
    def format(
        cls,
        prompt_type: PromptType,
        provider: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Retrieve template and interpolate keyword variables cleanly.
        """
        raw_template = cls.get_template(prompt_type, provider=provider)

        # Convert complex objects to string representation if needed
        formatted_kwargs: dict[str, str] = {}
        for key, val in kwargs.items():
            if isinstance(val, (dict, list)):
                import json
                formatted_kwargs[key] = json.dumps(val, indent=2)
            else:
                formatted_kwargs[key] = str(val) if val is not None else "None"

        try:
            return raw_template.format(**formatted_kwargs)
        except KeyError as exc:
            missing_var = str(exc).strip("'")
            raise KeyError(
                f"Missing required variable '{missing_var}' when formatting prompt '{prompt_type.value}'"
            ) from exc

    @classmethod
    def register_override(
        cls, provider: str, prompt_type: PromptType, template: str
    ) -> None:
        """
        Register a custom provider-specific prompt override (e.g. for Groq or Gemini optimized prompting).
        """
        if provider not in cls._CUSTOM_OVERRIDES:
            cls._CUSTOM_OVERRIDES[provider] = {}
        cls._CUSTOM_OVERRIDES[provider][prompt_type] = template

    @classmethod
    def list_prompts(cls) -> list[str]:
        """List all available prompt types."""
        return [pt.value for pt in PromptType]
