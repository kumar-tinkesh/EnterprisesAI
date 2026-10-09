"""Prompts for building agents and workflows from plain language.

Adapted from the AI Marketplace (``prompts/workflow_builder.py``,
``prompts/builder_assist.py``), whose wording was tuned against live runs.
Two deliberate differences, both from how this codebase works:

* Tools are not chosen from the whole catalog in one prompt. Each step's
  need is first narrowed by the hybrid tool search (vectors + BM25 +
  reranker) to a short candidate list, and the model only ever picks from
  that list — so a large catalog never overflows the prompt, and a tool the
  user may not use is never offered.
* A ``human_approval`` step here stops the run when rejected (the engine
  never routes a rejection onward), so the graph prompt doesn't ask for an
  approved/rejected condition after it.
"""
from __future__ import annotations

import json

PARALLEL_RULE = """- When the process has two or more genuinely INDEPENDENT sub-tasks that don't need each
  other's output first (e.g. "look up the customer's profile AND their order history") — wire them
  as parallel branches: one shared upstream step's edges go to EACH branch's first step, and the
  branches converge through an explicit "join" step before anything that needs all of them. A join
  takes an optional "join_policy": {"mode": "all"|"any"|"count", "min_required": <int, only for
  "count">}; "all" (the default) waits for every branch — use "any"/"count" only when the description
  implies partial results are still useful. A join must have 2+ incoming edges. Prefer ONE agent step
  whenever a single agent can plausibly cover the work; branch only when the sub-tasks are truly
  independent and each needs its own system or reasoning. The description naming 2+ distinct external
  systems is that signal.
- Outside a "condition" step's labelled branches and parallel branches, every step has AT MOST ONE
  outgoing edge, and every step must be reachable from the input step."""

SEQUENTIAL_RULE = """- Every step has AT MOST ONE outgoing edge (except a "condition" step's labelled branches), and
  every step must be reachable from the input step. When several steps are needed, chain them:
  input -> step A -> step B -> ... -> output."""


def generate_graph_prompt(description: str, *, allow_parallel: bool, max_nodes: int) -> str:
    join_example = ',\n    {"id": "n7", "type": "join", "join_policy": {"mode": "all"}}' if allow_parallel else ""
    types = "agent/condition/input/output/tool/human_approval" + ("/join" if allow_parallel else "")
    return f"""A user described a business process they want automated as an AI workflow.
Design it as a graph of steps and return ONLY JSON in exactly this shape:

{{
  "name": "short workflow name (2-5 words)",
  "nodes": [
    {{"id": "n1", "type": "input"}},
    {{"id": "n2", "type": "agent", "name": "...", "role": "...", "goal": "...", "instructions": "...", "needs": "..."}},
    {{"id": "n3", "type": "human_approval", "approval_message": "short message shown to the approver"}},
    {{"id": "n4", "type": "condition"}},
    {{"id": "n5", "type": "tool", "label": "...", "need": "the one external action this step performs, e.g. 'send the approved email via Gmail'"}},
    {{"id": "n6", "type": "output"}}{join_example}
  ],
  "edges": [
    {{"id": "e1", "source": "n1", "target": "n2"}},
    {{"id": "e2", "source": "n2", "target": "n4"}},
    {{"id": "e3", "source": "n4", "target": "n6", "condition": "short label for this branch"}}
  ]
}}

Rules:
- Exactly one "input" step and one "output" step; every path starts at the input and ends at the output.
- Use "agent" steps for anything that has to reason, decide, search or write. Give each: "name" (2-4
  words), "role" (one-line title), "goal" (one sentence: what THIS step does every run), "instructions"
  (2-4 sentences of expertise and guardrails), and "needs": one sentence naming what outside systems it
  must use ("read the latest Gmail messages and look up the sender in HubSpot"), or "" if it only works
  on the text it receives. When one agent covers several capabilities, its role, goal and needs must
  name every one of them.
- A step's goal and needs describe what THIS step does — a step that summarizes, reviews or formats what
  an EARLIER step fetched gets that content as its input and needs no fetching system of its own (and a
  step before a later "save to X" step doesn't need X either).
- Use a "tool" step ONLY for one fixed external action whose details are all in the text reaching it
  (send an email to a given address, post a chat message, save a file). Give it a short "label" and a
  "need" naming the system when the description does. If acting needs FINDING something first (which
  page, record, channel or id), use an agent step instead.
- Use a "human_approval" step right before something a person must sign off. Approving continues the
  workflow; rejecting stops it — so do NOT add an approved/rejected condition after it.
- Only add tool or approval steps the description actually asks for. When in doubt, prefer the simpler graph.
- Use a "condition" step only where the process genuinely branches (e.g. high vs low priority); label
  each outgoing edge with a short "condition". A condition with one outgoing edge is wrong. A condition
  may send work back to an earlier step for another pass ("Needs edits"), as long as another branch
  leaves the loop.
{PARALLEL_RULE if allow_parallel else SEQUENTIAL_RULE}
- {max_nodes} steps maximum. Prefer fewer, clearer steps.
- Do not invent step types outside {types}.

The business process the user described:
{description}
"""


def fix_graph_prompt(previous: str, problems: list[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems)
    return f"""The workflow graph you produced has these problems:
{listed}

Here it is again:
{previous}

Return the corrected graph as ONLY JSON in the same shape. Change only what's needed to fix the problems."""


def generate_agent_prompt(description: str) -> str:
    return f"""A user wants to build an AI agent. Based on their description below, return ONLY JSON with exactly these keys:
"name" (2-4 words), "role" (one-line professional title), "goal" (one clear sentence: what it should
accomplish every run), "instructions" (2-4 sentences of relevant expertise, personality and guardrails —
e.g. what it must never assume or do), "needs" (one sentence naming the outside systems or data it must
use, e.g. "read Gmail and create Jira tickets"; "" if it only answers from what it's told).

User's description:
{description}
"""


def pick_tools_prompt(step: str, candidates: list[str], *, single: bool) -> str:
    lines = "\n".join(candidates)
    if single:
        shape = '{"tool_id": "<one id from the list>" or null}'
        task = (
            "Pick the ONE tool that performs this step's action. A system that is only the data SOURCE for "
            "context is not the right pick if the action itself belongs to another system. Return null if "
            "nothing in the list performs it — never force a loose fit."
        )
    else:
        shape = '{"tool_ids": ["<id>", ...]}'
        task = (
            "Pick the tools this agent will actually need to do its job (usually 1-6). Include read tools it "
            "needs to look things up and the action tools its goal names; leave out tools for things it doesn't "
            "do. Return an empty list if it needs none."
        )
    return f"""{task}

Return ONLY JSON: {shape}

The step:
{step}

Candidate tools (id | system.tool: description):
{lines}
"""


def improve_text_prompt(field: str, text: str, context: str) -> str:
    guidance = {
        "name": "a short, memorable agent name (2-4 words)",
        "role": "a concise professional role/title for the agent (one line)",
        "goal": "a clear, specific statement of what the agent should accomplish on every run",
        "instructions": "2-4 sentences giving the agent relevant expertise, personality and guardrails (e.g. what it should never assume)",
        "prompt": "a clear, specific request to an AI agent — remove ambiguity and add obviously-missing detail without changing what's asked",
        "approval_message": "a short message telling an approver what to check before the workflow continues",
    }.get(field, "this text")
    context_block = f"Context:\n{context}\n\n" if context.strip() else ""
    return f"""You are helping a user write {guidance} for an AI agent or workflow they're configuring.

Rewrite their rough draft below into a polished, specific version. Keep their original intent — do not
invent unrelated capabilities. Return ONLY the improved text, no preamble, no quotes, no markdown.

{context_block}Draft to improve:
{text}
"""


EDIT_OPS_DOC = """Operations (each an object with an "op" key):
- {"op":"add_node","id":"new1","type":"agent|tool|human_approval|condition|output|join", ...fields}
    agent: "name","role","goal","instructions" (all four) and "needs" (one sentence, "" if none)
    tool: "label" and "need" (the ONE action it performs)    human_approval: "approval_message"
    join: "join_policy" {"mode":"all"|"any"|"count","min_required":<n>}
    Placement (optional): "after":<id> puts it right after that step (that step's outgoing lines move to it);
    "before":<id> puts it right in front of that step (that step's incoming lines move to it); both = between
    two directly connected steps. This rewires the lines itself — do NOT also add_edge/remove_edge for it.
    With neither, the step is added unconnected: do that whenever the user didn't say where it goes.
- {"op":"remove_node","id":"<id>"}   its neighbours are reconnected around it; the trigger can't be removed
- {"op":"move_node","id":"<id>","after":"<id>","before":"<id>"}   moves a step; old neighbours are reconnected
- {"op":"update_node","id":"<id>", ...fields}: label | approval_message | join_policy | tool_args |
    message_template | output_config {"format":"markdown|formatted|text|json","language":..,"header":..,"footer":..} |
    condition_config {"mode":"ai|rule","instructions":..,"rules":{"<target id>":{"field":"text","op":"contains|gt|...","value":..}},"default_branch":"<target id>"} |
    retry {"max_attempts":1-5}. null clears a field.
- {"op":"replace_agent","id":"<agent step id>","name":..,"role":..,"goal":..,"instructions":..,"needs":..}  only the fields that change
- {"op":"set_tool","id":"<tool step id>","need":"<the action it should now perform>"}
- {"op":"add_edge","source":"<id>","target":"<id>","condition":"<label, only out of a condition>"}
- {"op":"remove_edge","source":"<id>","target":"<id>"}
- {"op":"update_edge","source":"<id>","target":"<id>","condition":"<label or null>"}
- {"op":"replace_trigger","type":"input|manual_trigger|schedule_trigger","schedule":{"cron":"<5-field cron>","timezone":"<IANA>"}}
    "schedule" only with schedule_trigger, whenever the user says when it should run ("every weekday at 9am" ->
    "0 9 * * 1-5", "every Monday 8:30" -> "30 8 * * 1", "every 2 hours" -> "0 */2 * * *"). Omit "timezone"
    unless the user names one (the user's own is used). Also use it to change an existing schedule. At most every 5 minutes.
- {"op":"rename_workflow","name":"<new name>"}
- {"op":"set_config","config":{...}}: max_run_seconds, max_steps, on_node_failure ("abort"|"skip"|"retry"),
    node_retry_count (0-5), approvals {"read":bool,"edit":bool,"delete":bool}

Rules:
- Use the EXACT existing ids. New steps get temporary ids "new1", "new2", …; list a step's add_node before any
  operation that uses its id.
- Do the minimum: leave every step and setting the instruction doesn't mention alone. Never re-create an
  existing step to change it.
- Naming a service ("add Slack", "use Notion for this") is an edit to THIS workflow: add a step for it.
- If the message is a question or nothing needs to change, return "ops": [] and put your reply in "answer".

Return ONLY JSON: {"summary": "<one short sentence saying what you changed>", "answer": null, "ops": [ ... ]}
"""


def edit_prompt(name: str, node_lines: str, edge_lines: str, settings: dict, instruction: str, timezone: str = "UTC") -> str:
    return (
        "You are editing an EXISTING AI workflow on a visual canvas. The user gave ONE instruction. Return the\n"
        "smallest list of operations that carries it out.\n\n"
        f'Workflow name: "{name}"\n'
        f"The user's timezone: {timezone}\n"
        f"Steps (use these exact ids):\n{node_lines}\n\n"
        f"Connections (source -> target):\n{edge_lines}\n\n"
        f"Workflow settings: {json.dumps(settings) if settings else '(defaults)'}\n\n"
        f"{EDIT_OPS_DOC}\n"
        f'The user\'s instruction:\n"""\n{instruction}\n"""\n'
    )
