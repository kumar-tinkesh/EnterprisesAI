"""
Unit tests for Prompt Registry & System Prompt Management.
"""

import pytest
from apps.llm_gateway.prompts import PromptRegistry, PromptType


def test_prompt_registry_list_prompts():
    prompts = PromptRegistry.list_prompts()
    assert "react_agent" in prompts
    assert "ai_designer" in prompts
    assert "rag_grounded_qa" in prompts


def test_prompt_registry_format_react_agent():
    formatted = PromptRegistry.format(
        PromptType.REACT_AGENT,
        agent_goal="Process invoice #1234",
        bound_tools=["accounting.getInvoice", "slack.notify"],
        knowledge_context="Accounting policy v1",
        memory_context="Initial run",
    )
    assert "Process invoice #1234" in formatted
    assert "accounting.getInvoice" in formatted
    assert "Accounting policy v1" in formatted


def test_prompt_registry_missing_variable():
    with pytest.raises(KeyError) as exc_info:
        PromptRegistry.format(PromptType.REACT_AGENT, agent_goal="Test")
    assert "Missing required variable" in str(exc_info.value)


def test_prompt_registry_override():
    PromptRegistry.register_override(
        provider="groq",
        prompt_type=PromptType.REACT_AGENT,
        template="Custom Groq ReAct Prompt for {agent_goal}. Tools: {bound_tools}. Knowledge: {knowledge_context}. Memory: {memory_context}.",
    )

    formatted = PromptRegistry.format(
        PromptType.REACT_AGENT,
        provider="groq",
        agent_goal="Fast reasoning task",
        bound_tools=[],
        knowledge_context="None",
        memory_context="None",
    )

    assert "Custom Groq ReAct Prompt for Fast reasoning task" in formatted
