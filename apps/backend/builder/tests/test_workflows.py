"""Workflow runs end to end: scheduling, every step type, failure policies,
approvals, loops, crash recovery — against the real demo MCP server.

The model is a routed fake: each request is answered by the route whose
marker appears in it (an agent's "You are <Name>", a condition prompt, the
tool-argument prompt, the output compose prompt), because parallel steps make
the order of requests nondeterministic.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from apps.llm_gateway.types import CompletionResponse, TokenUsage
from builder.tests.test_runs import HANG, demo, get_run, kill, reply, runtime, worker  # noqa: F401  (fixtures)

WF = "/api/v1/builder/workflows"


class RoutedGateway:
    def __init__(self):
        self.routes: list[list] = []
        self.requests = []
        self.hung = asyncio.Event()
        self.barrier: dict[str, asyncio.Event] = {}

    def when(self, marker: str, *responses):
        self.routes.append([marker, list(responses)])
        return self

    def calls(self, marker: str) -> list:
        return [r for r in self.requests if marker in self._blob(r)]

    @staticmethod
    def _blob(request) -> str:
        return "\n".join(m.content or "" for m in request.messages[:2])

    async def complete(self, request, provider=None, fallback=True):
        self.requests.append(request)
        blob = self._blob(request)
        for marker, responses in self.routes:
            if marker in blob:
                item = responses.pop(0) if len(responses) > 1 else responses[0]
                if item is HANG:
                    self.hung.set()
                    await asyncio.Event().wait()
                if callable(item):
                    item = await item()
                if isinstance(item, BaseException):
                    raise item
                return item if isinstance(item, CompletionResponse) else reply(item)
        raise AssertionError(f"no route for request: {blob[:300]}")


def label(text: str) -> CompletionResponse:
    return CompletionResponse(content=json.dumps({"label": text}), usage=TokenUsage(3, 2, 5))


@pytest.fixture
def llm(monkeypatch):
    gw = RoutedGateway()
    monkeypatch.setattr("builder.agents.runtime._gateway", lambda: gw)
    return gw


async def agent(client, name: str, demo=None, tools: list[str] = (), **config) -> str:
    body = {"name": name, "role": "assistant", "goal": f"{name} things", "config": {**config}}
    if tools:
        body["config"]["tool_ids"] = [f"mcp:{demo.id}:{t}" for t in tools]
    r = await client.post("/api/v1/builder/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def workflow(client, nodes: list[dict], edges: list[tuple], **config) -> dict:
    body = {
        "name": "Flow",
        "nodes": nodes,
        "edges": [{"id": f"e{i}", "source": e[0], "target": e[1], **({"condition": e[2]} if len(e) > 2 else {})} for i, e in enumerate(edges)],
        "config": config,
    }
    r = await client.post(WF, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def start(client, wf: dict, text: str = "do it", **variables) -> str:
    r = await client.post(f"{WF}/{wf['id']}/runs", json={"input": text, "variables": variables})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def nodes_by_id(run: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for n in run["nodes"]:
        out.setdefault(n["node_id"], []).append(n)
    return out


INPUT = {"id": "in", "type": "input"}
OUTPUT = {"id": "out", "type": "output"}


# ── Flow ─────────────────────────────────────────────────────────────────────


async def test_linear_workflow(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "A short draft about cats.")
    wf = await workflow(tenant_client, [INPUT, {"id": "w", "type": "agent", "agent_id": writer}, OUTPUT], [("in", "w"), ("w", "out")])
    run_id = await start(tenant_client, wf, "write about cats")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded", run
    assert run["output_text"] == "A short draft about cats." and run["output"]["final_node"] == "out"
    assert {n["node_id"]: n["status"] for n in run["nodes"]} == {"in": "succeeded", "w": "succeeded", "out": "succeeded"}
    assert run["name"] == "Flow"


async def test_parallel_steps_run_together_and_the_output_composes(tenant_client, llm, runtime):
    alpha, beta = await agent(tenant_client, "Alpha"), await agent(tenant_client, "Beta")
    both_started = asyncio.Event()
    started: set[str] = set()

    def gate(name: str, answer: str):
        async def respond():
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 10)  # deadlocks unless both run at once
            return reply(answer)
        return respond

    llm.when("You are Alpha", gate("a", "Alpha facts")).when("You are Beta", gate("b", "Beta facts"))
    llm.when("Several steps of a workflow", "One combined answer.")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "a", "type": "agent", "agent_id": alpha}, {"id": "b", "type": "agent", "agent_id": beta}, OUTPUT],
        [("in", "a"), ("in", "b"), ("a", "out"), ("b", "out")],
    )
    run_id = await start(tenant_client, wf)
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "One combined answer."
    compose = llm.calls("Several steps of a workflow")[0].messages[0].content
    assert "Alpha facts" in compose and "Beta facts" in compose


async def test_rule_condition_takes_one_branch(tenant_client, llm, runtime):
    esc, filer = await agent(tenant_client, "Escalator"), await agent(tenant_client, "Filer")
    llm.when("You are Escalator", "Paged the on-call.").when("You are Filer", "Filed it.")
    wf = await workflow(
        tenant_client,
        [
            INPUT,
            {"id": "c", "type": "condition", "condition_config": {"mode": "rule", "rules": {"big": {"field": "text", "op": "contains", "value": "urgent"}}, "default_branch": "small"}},
            {"id": "big", "type": "agent", "agent_id": esc},
            {"id": "small", "type": "agent", "agent_id": filer},
            OUTPUT,
        ],
        [("in", "c"), ("c", "big", "Urgent"), ("c", "small"), ("big", "out"), ("small", "out")],
    )
    run_id = await start(tenant_client, wf, "URGENT: checkout is down")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "Paged the on-call."
    assert "small" not in nodes_by_id(run)  # never ran
    assert not llm.calls("You are Filer")


async def test_ai_condition_review_loop(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "draft one", "draft two")
    llm.when("Outcome labels", label("Needs edits"), label("Approved"))
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer, "label": "Write"}, {"id": "c", "type": "condition", "label": "Review"}, OUTPUT],
        [("in", "w"), ("w", "c"), ("c", "w", "Needs edits"), ("c", "out", "Approved")],
    )
    run_id = await start(tenant_client, wf, "write a tagline")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "draft two"
    assert [n["attempt"] for n in nodes_by_id(run)["w"]] == [1, 2]
    second_round = llm.calls("You are Writer")[-1].messages[1].content
    assert "draft one" in second_round  # the writer saw its first draft


async def test_loop_limit_stops_a_run_that_never_exits(tenant_client, llm, runtime):
    writer = await agent(tenant_client, "Writer")
    llm.when("You are Writer", "again")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "w", "type": "agent", "agent_id": writer}, {"id": "c", "type": "condition", "condition_config": {"mode": "rule", "rules": {"out": {"field": "text", "op": "contains", "value": "never"}}, "default_branch": "w"}}, OUTPUT],
        [("in", "w"), ("w", "c"), ("c", "w"), ("c", "out", "Done")],
        max_steps=7,
    )
    run_id = await start(tenant_client, wf)
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "failed" and "Stopped after 7 steps" in run["error"]


# ── Tool steps ───────────────────────────────────────────────────────────────


async def test_tool_step_waits_for_approval_and_passes_its_input_on(tenant_client, demo, llm, runtime):
    wf = await workflow(tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:send_note"}, OUTPUT], [("in", "t"), ("t", "out")])
    run_id = await start(tenant_client, wf, "hello world")
    w = worker(runtime)
    await w.drain()
    assert (await get_run(tenant_client, run_id))["status"] == "waiting"
    [ask] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    assert ask["kind"] == "tool_call" and ask["payload"]["arguments"] == {"text": "hello world"}
    assert "Workflow step" in ask["payload"]["message"]
    await tenant_client.post(f"/api/v1/builder/approvals/{ask['id']}", json={"decision": "approve"})
    await w.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "hello world"  # what was sent
    assert runtime["notes"].read_text() == "hello world\n"


async def test_missing_tool_input_is_asked_for_never_invented(tenant_client, demo, llm, runtime):
    llm.when("is calling the tool", reply(json.dumps({"to": "boss@made-up.example"})))
    wf = await workflow(
        tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:email_report"}, OUTPUT],
        [("in", "t"), ("t", "out")], approvals={"read": False, "edit": False, "delete": True},
    )
    run_id = await start(tenant_client, wf, "Weekly numbers are up 5%")
    w = worker(runtime)
    await w.drain()
    [ask] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    assert ask["kind"] == "missing_input" and ask["payload"]["missing"] == ["to"]
    url = f"/api/v1/builder/approvals/{ask['id']}"
    assert (await tenant_client.post(url, json={"decision": "approve"})).status_code == 422
    assert (await tenant_client.post(url, json={"decision": "edit", "arguments": {"to": 7}})).status_code == 422
    assert (await tenant_client.post(url, json={"decision": "edit", "arguments": {"to": "ceo@acme.com"}})).status_code == 200
    await w.drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    assert runtime["notes"].read_text() == "to=ceo@acme.com body=Weekly numbers are up 5%\n"


async def test_identifier_in_the_text_is_used(tenant_client, demo, llm, runtime):
    llm.when("is calling the tool", reply(json.dumps({"to": "ceo@acme.com"})))
    wf = await workflow(
        tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:email_report"}, OUTPUT],
        [("in", "t"), ("t", "out")], approvals={"read": False, "edit": False, "delete": True},
    )
    run_id = await start(tenant_client, wf, "Send the summary to ceo@acme.com")
    await worker(runtime).drain()
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"
    assert runtime["notes"].read_text().startswith("to=ceo@acme.com")


# ── Approval step ────────────────────────────────────────────────────────────


async def test_human_approval_can_edit_the_text(tenant_client, llm, runtime):
    drafter = await agent(tenant_client, "Drafter")
    llm.when("You are Drafter", "rough draft")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "d", "type": "agent", "agent_id": drafter}, {"id": "h", "type": "human_approval", "approval_message": "Check the draft"}, OUTPUT],
        [("in", "d"), ("d", "h"), ("h", "out")],
    )
    run_id = await start(tenant_client, wf)
    w = worker(runtime)
    await w.drain()
    [ask] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    assert ask["kind"] == "human_step" and ask["payload"]["text"] == "rough draft" and ask["payload"]["message"] == "Check the draft"
    await tenant_client.post(f"/api/v1/builder/approvals/{ask['id']}", json={"decision": "edit", "arguments": {"text": "polished draft"}})
    await w.drain()
    assert (await get_run(tenant_client, run_id))["output_text"] == "polished draft"


async def test_rejected_approval_stops_the_run_even_with_skip(tenant_client, llm, runtime):
    wf = await workflow(
        tenant_client, [INPUT, {"id": "h", "type": "human_approval"}, OUTPUT], [("in", "h"), ("h", "out")], on_node_failure="skip",
    )
    run_id = await start(tenant_client, wf)
    w = worker(runtime)
    await w.drain()
    [ask] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    await tenant_client.post(f"/api/v1/builder/approvals/{ask['id']}", json={"decision": "reject"})
    await w.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "failed" and "rejected" in run["error"]


# ── Failure policies ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("policy,expected", [("abort", "failed"), ("skip", "succeeded")])
async def test_failure_policy(tenant_client, demo, llm, runtime, policy, expected):
    wf = await workflow(tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:fail", "label": "Check"}, OUTPUT], [("in", "t"), ("t", "out")], on_node_failure=policy)
    run_id = await start(tenant_client, wf, "carry on")
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == expected
    if expected == "failed":
        assert 'Step "Check" failed' in run["error"] and "boom" in run["error"]
    else:
        assert run["output_text"] == "carry on"  # the failed step passed its input on


async def test_retry_then_give_up(tenant_client, demo, llm, runtime):
    wf = await workflow(tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:fail", "retry": {"max_attempts": 3}}, OUTPUT], [("in", "t"), ("t", "out")])
    run_id = await start(tenant_client, wf)
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "failed"
    assert [n["attempt"] for n in nodes_by_id(run)["t"]] == [1, 2, 3]
    assert len(run["tool_calls"]) == 3


async def test_join_any_goes_on_without_a_failed_branch(tenant_client, demo, llm, runtime):
    helper = await agent(tenant_client, "Helper")
    llm.when("You are Helper", "helper result")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "x", "type": "tool", "tool_id": f"mcp:{demo.id}:fail"}, {"id": "y", "type": "agent", "agent_id": helper},
         {"id": "j", "type": "join", "join_policy": {"mode": "any"}}, OUTPUT],
        [("in", "x"), ("in", "y"), ("x", "j"), ("y", "j"), ("j", "out")],
    )
    run_id = await start(tenant_client, wf)
    await worker(runtime).drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "helper result"
    assert nodes_by_id(run)["x"][0]["status"] == "failed"


# ── Durability ───────────────────────────────────────────────────────────────


async def test_crash_mid_workflow_resumes_without_redoing_finished_steps(db, tenant_client, demo, llm, runtime):
    noter = await agent(tenant_client, "Noter", demo, ["send_note"], approvals={"read": False, "edit": False, "delete": True})
    closer = await agent(tenant_client, "Closer")
    llm.when("You are Noter", reply(calls=[("demo__send_note", {"text": "once"})]), "noted")
    llm.when("You are Closer", HANG, "closed")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "n", "type": "agent", "agent_id": noter}, {"id": "c", "type": "agent", "agent_id": closer}, OUTPUT],
        [("in", "n"), ("n", "c"), ("c", "out")],
        # The stricter of the agent's and the workflow's approval rules applies.
        approvals={"read": False, "edit": False, "delete": True},
    )
    run_id = await start(tenant_client, wf)
    w1 = worker(runtime, "w1")
    await w1.start(reaper=False)
    await asyncio.wait_for(llm.hung.wait(), 30)
    await kill(w1, db, run_id)

    w2 = worker(runtime, "w2")
    await w2.reap()
    await w2.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"] == "closed"
    assert run["recoveries"] == 1
    assert runtime["notes"].read_text() == "once\n"
    assert len(llm.calls("You are Noter")) == 2  # its two model turns, never repeated
    assert [n["attempt"] for n in nodes_by_id(run)["c"]] == [1]  # resumed, not restarted


async def test_a_run_keeps_the_definition_it_started_with(tenant_client, llm, runtime):
    wf = await workflow(tenant_client, [INPUT, {"id": "h", "type": "human_approval"}, OUTPUT], [("in", "h"), ("h", "out")])
    run_id = await start(tenant_client, wf, "original")
    w = worker(runtime)
    await w.drain()
    # Edit the workflow while the run waits: drop the output step.
    r = await tenant_client.patch(f"{WF}/{wf['id']}", json={"nodes": [INPUT, {"id": "h", "type": "human_approval"}], "edges": [{"id": "e0", "source": "in", "target": "h"}]})
    assert r.status_code == 200
    [ask] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    await tenant_client.post(f"/api/v1/builder/approvals/{ask['id']}", json={"decision": "approve"})
    await w.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output"]["final_node"] == "out" and run["definition_version"] == 1


# ── Starting a run ───────────────────────────────────────────────────────────


async def test_start_checks_connections_and_required_inputs(db, tenant_client, demo, llm, runtime, tenant_user):
    from vendor.services import mcp_auth

    helper = await agent(tenant_client, "Helper")
    llm.when("You are Helper", "ok")
    wf = await workflow(
        tenant_client,
        [{"id": "in", "type": "input", "variables": [{"name": "customer", "required": True}]}, {"id": "a", "type": "agent", "agent_id": helper}, OUTPUT],
        [("in", "a"), ("a", "out")],
    )
    r = await tenant_client.post(f"{WF}/{wf['id']}/runs", json={"input": "go"})
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "missing_variable"
    run_id = await start(tenant_client, wf, "go", customer="Acme")
    await worker(runtime).drain()
    assert "customer: Acme" in llm.calls("You are Helper")[0].messages[1].content

    tool_wf = await workflow(tenant_client, [INPUT, {"id": "t", "type": "tool", "tool_id": f"mcp:{demo.id}:echo"}], [("in", "t")])
    await mcp_auth.delete_user_credential(db, server_id=demo.id, user_id=tenant_user.id)
    await db.commit()
    r = await tenant_client.post(f"{WF}/{tool_wf['id']}/runs", json={"input": "x"})
    assert r.status_code == 422 and r.json()["problems"][0]["code"] == "not_connected"
    assert (await get_run(tenant_client, run_id))["status"] == "succeeded"


async def test_a_waiting_branch_does_not_hold_up_the_others(tenant_client, llm, runtime):
    helper = await agent(tenant_client, "Helper")
    llm.when("You are Helper", "helper result")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "h", "type": "human_approval"}, {"id": "a", "type": "agent", "agent_id": helper},
         {"id": "j", "type": "join"}, OUTPUT],
        [("in", "h"), ("in", "a"), ("h", "j"), ("a", "j"), ("j", "out")],
    )
    run_id = await start(tenant_client, wf, "go")
    w = worker(runtime)
    await w.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "waiting"
    assert nodes_by_id(run)["a"][0]["status"] == "succeeded"  # ran while h waited
    [ask] = (await tenant_client.get("/api/v1/builder/approvals")).json()
    await tenant_client.post(f"/api/v1/builder/approvals/{ask['id']}", json={"decision": "approve"})
    await w.drain()
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and "helper result" in run["output_text"]
    assert len(llm.calls("You are Helper")) == 1  # not run again on resume
