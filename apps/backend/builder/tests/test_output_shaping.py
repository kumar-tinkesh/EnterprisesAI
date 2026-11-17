"""The output step's shaping: custom sections, a fixed title, the owner's instructions, and the editor's
preview of other settings on an earlier run's texts."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from builder.tests.test_runs import get_run, runtime, worker  # noqa: F401  (fixtures)
from builder.tests.test_workflows import INPUT, WF, agent, llm, start, workflow  # noqa: F401  (fixtures)

FORMATTED = "Rewrite the workflow answer below as a clean"
COMPOSE = "Several steps of a workflow"
JSON_SHAPE = "Convert the workflow answer below into ONE JSON"


def _prompt(llm, marker: str) -> str:
    (request,) = llm.calls(marker)
    return request.messages[0].content


async def _run(tenant_client, llm, runtime, output_config: dict) -> tuple[dict, str]:
    researcher = await agent(tenant_client, "Researcher")
    llm.when("You are Researcher", "| Company | Score |\n|---|---|\n| Acme | 80 |")
    wf = await workflow(
        tenant_client,
        [INPUT, {"id": "a", "type": "agent", "agent_id": researcher}, {"id": "out", "type": "output", "output_config": output_config}],
        [("in", "a"), ("a", "out")],
    )
    run_id = await start(tenant_client, wf, "find leads")
    await worker(runtime).drain()
    return wf, run_id


async def test_custom_sections_title_and_instructions_shape_the_report(tenant_client, llm, runtime):
    llm.when(FORMATTED, "# Leads\n\n## Ranked leads\n| Company | Score |\n|---|---|\n| Acme | 80 |")
    _, run_id = await _run(tenant_client, llm, runtime, {
        "format": "formatted", "title": "Leads – {{date}}", "instructions": "At most 10 leads.",
        "custom_sections": [{"title": "Ranked leads", "hint": "one table: company and score"}, {"title": "Next steps"}],
    })
    run = await get_run(tenant_client, run_id)
    assert run["status"] == "succeeded" and run["output_text"].startswith("# Leads")
    prompt = _prompt(llm, FORMATTED)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert f'"# Leads – {today}"' in prompt
    assert '"## Ranked leads": one table: company and score' in prompt and '"## Next steps"' in prompt
    assert '"## Summary"' not in prompt  # the presets are replaced, not added to
    assert "At most 10 leads." in prompt
    # What reached each step is part of the run's view.
    out = next(n for n in run["nodes"] if n["node_id"] == "out")
    assert "Acme" in out["input_text"]


async def test_instructions_give_a_single_answer_one_tidy_pass(tenant_client, llm, runtime):
    llm.when(COMPOSE, "Acme – 80")
    _, run_id = await _run(tenant_client, llm, runtime, {"format": "markdown", "instructions": "One line per company."})
    assert (await get_run(tenant_client, run_id))["output_text"] == "Acme – 80"
    assert "One line per company." in _prompt(llm, COMPOSE)


async def test_preview_reshapes_an_earlier_run_without_running_it_again(tenant_client, llm, runtime):
    wf, run_id = await _run(tenant_client, llm, runtime, {"format": "markdown"})
    researcher_calls = len(llm.calls("You are Researcher"))
    llm.when(JSON_SHAPE, json.dumps({"leads": [{"company": "Acme", "score": 80}]}))

    r = await tenant_client.post(f"{WF}/{wf['id']}/output-preview", json={
        "run_id": run_id, "node_id": "out", "output_config": {"format": "json", "instructions": "a leads array"},
    })
    assert r.status_code == 200, r.text
    assert json.loads(r.json()["text"]) == {"leads": [{"company": "Acme", "score": 80}]}
    assert "a leads array" in _prompt(llm, JSON_SHAPE)
    assert len(llm.calls("You are Researcher")) == researcher_calls  # nothing ran again

    bad = await tenant_client.post(f"{WF}/{wf['id']}/output-preview", json={"run_id": run_id, "node_id": "out", "output_config": {"format": "pdf"}})
    assert bad.status_code == 422
    never = await tenant_client.post(f"{WF}/{wf['id']}/output-preview", json={"run_id": run_id, "node_id": "nope", "output_config": {}})
    assert never.status_code == 409
    other = await tenant_client.post(f"{WF}/{wf['id']}/output-preview", json={"run_id": "not-a-run", "node_id": "out", "output_config": {}})
    assert other.status_code == 404


async def test_custom_sections_are_checked_on_save(tenant_client):
    body = {"name": "Flow", "nodes": [INPUT, {"id": "out", "type": "output", "output_config": {"format": "formatted", "custom_sections": [{"title": " "}]}}],
            "edges": [{"id": "e0", "source": "in", "target": "out"}], "config": {}}
    r = await tenant_client.post(WF, json=body)
    assert r.status_code == 422 and "custom section needs a title" in r.text
