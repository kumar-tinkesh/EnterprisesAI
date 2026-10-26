"""
Enterprise AI Platform — Unified Prompt Management Subpackage.
"""

from apps.llm_gateway.prompts.registry import PromptRegistry, PromptType
from apps.llm_gateway.prompts.templates import (
    SYSTEM_AI_DESIGNER,
    SYSTEM_GRAPH_PATCHER,
    SYSTEM_REACT_AGENT,
    SYSTEM_RAG_QUERY_REWRITE,
    SYSTEM_RAG_GROUNDED_QA,
    SYSTEM_GUARDRAIL_INSPECTOR,
    SYSTEM_EVALUATION_JUDGE,
    SYSTEM_DOCUMENT_EXTRACTION,
    SYSTEM_AGENT_COMPILER,
)

__all__ = [
    "PromptRegistry",
    "PromptType",
    "SYSTEM_AI_DESIGNER",
    "SYSTEM_GRAPH_PATCHER",
    "SYSTEM_REACT_AGENT",
    "SYSTEM_RAG_QUERY_REWRITE",
    "SYSTEM_RAG_GROUNDED_QA",
    "SYSTEM_GUARDRAIL_INSPECTOR",
    "SYSTEM_EVALUATION_JUDGE",
    "SYSTEM_DOCUMENT_EXTRACTION",
    "SYSTEM_AGENT_COMPILER",
]

