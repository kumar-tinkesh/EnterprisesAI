"""A workflow's front desk (builder.workflows.front_desk): small talk and general
questions get a direct answer and no step runs; anything else runs the workflow."""
from __future__ import annotations

import json

import pytest

from apps.llm_gateway.types import CompletionResponse, TokenUsage
from builder.agents.config import AgentConfig
from builder.agents.prompts import system_prompt
from builder.tests.test_runs import demo, get_run, runtime, worker  # noqa: F401  (fixtures)
from builder.tests.test_workflows import INPUT, OUTPUT, agent, llm, start, workflow  # noqa: F401  (fixtures)

DESK = "You are the front desk"


def desk(route: str, answer: str = "") -> CompletionResponse:
    body = {"route": route, **({"answer": answer} if answer else {})}
    return CompletionResponse(content=json.dumps(body), usage=TokenUsage(7, 5, 12))


async def _mail_flow(client) -> dict:
    summarizer = await agent(client, "Summarizer")
    return await workflow(
        client, [INPUT, {"id": "s", "type": "agent", "agent_id": summarizer}, OUTPUT], [("in", "s"), ("s", "out")],
    )


@pytest.mark.front_desk
async def test_a_greeting_is_answered_without_running_any_step(tenant_client, llm, runtime):
    wf = await _mail_flow(tenant_client)
    answer = "Hello! How can I help?\n\nI can:\n- summarize things for you"
    llm.when(DESK, desk("general", answer))
    llm.when("You are Summarizer", "should not run")

    run_id = await start(tenant_client, wf, "hi")
    await worker(runtime).drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == answer
    assert run["output"]["front_desk"] == "general"
    assert llm.calls("You are Summarizer") == [] and run["nodes"] == []
    assert run["prompt_tokens"] == 7 and run["completion_tokens"] == 5
    # It was told what the workflow does, from the steps' own goals.
    [asked] = llm.calls(DESK)
    assert "Summarizer — Summarizer things" in asked.messages[0].content and "<message>\nhi\n</message>" in asked.messages[0].content


@pytest.mark.front_desk
async def test_a_request_for_the_workflow_runs_it(tenant_client, llm, runtime):
    wf = await _mail_flow(tenant_client)
    llm.when(DESK, desk("task"))
    llm.when("You are Summarizer", "Your inbox, summarized.")

    run_id = await start(tenant_client, wf, "summarize my mail")
    await worker(runtime).drain()

    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "Your inbox, summarized."
    assert len(llm.calls(DESK)) == 1


@pytest.mark.front_desk
async def test_an_unreadable_decision_runs_the_workflow(tenant_client, llm, runtime):
    wf = await _mail_flow(tenant_client)
    llm.when(DESK, "not json")
    llm.when("You are Summarizer", "Ran anyway.")
    run_id = await start(tenant_client, wf, "hi")
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["output_text"] == "Ran anyway."


@pytest.mark.front_desk
async def test_no_front_desk_when_turned_off_or_given_inputs(tenant_client, llm, runtime):
    summarizer = await agent(tenant_client, "Summarizer")
    nodes, edges = [INPUT, {"id": "s", "type": "agent", "agent_id": summarizer}, OUTPUT], [("in", "s"), ("s", "out")]
    llm.when(DESK, desk("general", "Hello!"))
    llm.when("You are Summarizer", "Ran.")

    off = await workflow(tenant_client, nodes, edges, answer_general_questions=False)
    on = await workflow(tenant_client, nodes, edges)
    first = await start(tenant_client, off, "hi")
    second = await start(tenant_client, on, "hi", topic="mail")  # filled-in inputs: a request, not chat
    await worker(runtime).drain()

    assert (await get_run(tenant_client, first))["output_text"] == "Ran."
    assert (await get_run(tenant_client, second))["output_text"] == "Ran."
    assert llm.calls(DESK) == []


def test_agents_answer_general_questions_unless_turned_off():
    agent_def = {"name": "Helper", "role": "assistant", "goal": "Help with LinkedIn"}
    on = system_prompt(agent_def, AgentConfig(), has_tools=False, has_knowledge=False)
    off = system_prompt(agent_def, AgentConfig.model_validate({"chat": {"answer_general": False}}), has_tools=False, has_knowledge=False)
    assert "general question your goal isn't for" in on and "what you can help with" in on
    assert "general question" not in off


def test_agents_and_the_front_desk_say_who_made_them(monkeypatch):
    from builder.config import get_builder_settings
    from builder.workflows.front_desk import _prompt

    agent_def = {"name": "Helper", "role": "assistant", "goal": "Help"}
    prompt = system_prompt(agent_def, AgentConfig(), has_tools=False, has_knowledge=False)
    assert "developed by Abhishek" in prompt and "Never say you were made by" in prompt and "OpenAI" in prompt
    assert "developed by Abhishek" in _prompt("Flow", "", ["Search"], "who made you?", [])

    monkeypatch.setattr(get_builder_settings(), "AI_DEVELOPER", "Acme Labs")
    assert "developed by Acme Labs" in system_prompt(agent_def, AgentConfig(), has_tools=False, has_knowledge=False)
    monkeypatch.setattr(get_builder_settings(), "AI_DEVELOPER", "")
    assert "developed by" not in system_prompt(agent_def, AgentConfig(), has_tools=False, has_knowledge=False)
    assert "developed by" not in _prompt("Flow", "", ["Search"], "hi", [])


async def test_a_workflows_steps_keep_their_thinking_under_their_names(tenant_client, llm, runtime):
    researcher, writer = await agent(tenant_client, "Researcher"), await agent(tenant_client, "Writer")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "r", "type": "agent", "agent_id": researcher}, {"id": "w", "type": "agent", "agent_id": writer}, OUTPUT],
        [("in", "r"), ("r", "w"), ("w", "out")],
    )
    found, written = CompletionResponse(content="Facts.", usage=TokenUsage(1, 1, 2)), CompletionResponse(content="Story.", usage=TokenUsage(1, 1, 2))
    found.reasoning, written.reasoning = "Look up facts.", "Turn them into a story."
    llm.when("You are Researcher", found)
    llm.when("You are Writer", written)

    run_id = await start(tenant_client, wf, "write about tortoises")
    await worker(runtime).drain()

    run = await get_run(tenant_client, run_id)
    assert run["output_text"] == "Story."
    assert run["output"]["reasoning"] == "Researcher\nLook up facts.\n\nWriter\nTurn them into a story."


def test_the_plan_says_which_language_unless_the_agent_has_one():
    from builder.agents.prompts import PLAN_LANGUAGE_RULE, PLAN_RULE

    agent_def = {"name": "Helper", "role": "assistant", "goal": "Help"}
    auto = system_prompt(agent_def, AgentConfig(), has_tools=False, has_knowledge=False, plan=True)
    hindi = system_prompt(agent_def, AgentConfig.model_validate({"response": {"language": "Hindi"}}), has_tools=False, has_knowledge=False, plan=True)
    assert PLAN_RULE in auto and PLAN_LANGUAGE_RULE in auto and "use English" in auto
    assert PLAN_RULE in hindi and PLAN_LANGUAGE_RULE not in hindi and "Answer in Hindi" in hindi
