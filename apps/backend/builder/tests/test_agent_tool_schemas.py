"""Tool schemas are reshaped so every LLM provider accepts them (OpenAI/Azure
reject oneOf/anyOf/allOf/enum/const/not at the top level of a function's
parameters, and one bad tool fails the whole request)."""
from __future__ import annotations

from builder.agents.tools import AgentTool, function_definitions, provider_safe_parameters

# The real tavily_feedback schema's shape: "give session_id or request_id".
TAVILY_FEEDBACK = {
    "type": "object",
    "properties": {"session_id": {"type": "string"}, "request_id": {"type": "string"}, "agent_score": {"type": ["number", "string"]}},
    "anyOf": [{"required": ["session_id"]}, {"required": ["request_id"]}],
}


def _tool(schema: dict | None) -> AgentTool:
    return AgentTool("web_search__tavily_feedback", "s1", "web search", "tavily_feedback", "Rate a search.", schema, None)


def test_top_level_anyof_is_dropped_and_described():
    params, note = provider_safe_parameters(TAVILY_FEEDBACK)
    assert not {"anyOf", "oneOf", "allOf", "enum", "const", "not"} & params.keys()
    assert params["type"] == "object"
    assert params["properties"] == TAVILY_FEEDBACK["properties"]
    assert note == "Provide session_id; or request_id."
    # The stored schema itself is left alone.
    assert "anyOf" in TAVILY_FEEDBACK


def test_function_definition_carries_the_note():
    [d] = function_definitions([_tool(TAVILY_FEEDBACK)], with_knowledge=False)
    assert d["description"] == "[web search] Rate a search. Provide session_id; or request_id."
    assert "anyOf" not in d["parameters"]


def test_ordinary_and_missing_schemas():
    ok = {"type": "object", "properties": {"q": {"type": "string", "enum": ["a", "b"]}}, "required": ["q"]}
    assert provider_safe_parameters(ok) == (ok, "")  # nested enum is fine
    assert provider_safe_parameters(None) == ({"type": "object", "properties": {}}, "")
    assert provider_safe_parameters({"oneOf": [{"type": "string"}]}) == ({"type": "object", "properties": {}}, "")
