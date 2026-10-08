"""Edit an open workflow from one instruction, as small operations.

Asking the model for a list of operations ("add a Slack step after the
summary") instead of a rewritten graph keeps every step it didn't mention
byte-for-byte the same — ids, agents, tool arguments, layout. Ported in
design from the AI Marketplace's ``workflows/edit_ops.py``.

Two passes:
1. ``resolve`` (async): for each op that needs the outside world — a tool
   step's need -> a tool (hybrid search + pick), an agent step -> a draft
   agent with its tools — work it out up front.
2. ``Editor.apply`` (pure): apply the ops to plain node/edge dicts.

An op that can't be applied raises ``EditError`` with a message for the
person; the endpoint feeds it back to the model for one repair attempt.
The result is a draft — the person sees it on the canvas and saves it.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser

from builder.assist.drafts import agent_spec
from builder.assist.llm import Usage
from builder.assist.tools import pick_agent_tools, pick_tool
from builder.graph.schema import NODE_TYPES, TRIGGER_TYPES, WorkflowConfig

MAX_EDIT_NODES = 40
ADDABLE = NODE_TYPES - TRIGGER_TYPES
_NODE_FIELDS = {
    "label", "approval_message", "join_policy", "tool_args", "message_template", "output_config",
    "condition_config", "retry", "config_overrides", "schedule", "variables",
}


class EditError(Exception):
    pass


def _s(value: Any) -> str:
    return str(value).strip() if value is not None else ""


@dataclass
class Resolved:
    """What pass 1 worked out, by op index."""

    tools: dict[int, dict | None] = field(default_factory=dict)  # tool candidate dict, or None = nothing fits
    agents: dict[int, dict] = field(default_factory=dict)  # draft_agent dicts


async def resolve(
    db: AsyncSession, user: CurrentUser, ops: list, nodes: list[dict], existing_agents: dict[str, dict], usage: Usage, description: str
) -> Resolved:
    out = Resolved()
    by_id = {n["id"]: n for n in nodes}
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if (kind == "add_node" and op.get("type") in ("tool", "notification")) or kind == "set_tool":
            need = _s(op.get("need") or op.get("label") or op.get("name"))
            picked = await pick_tool(db, user, need, f'Context: a step in the workflow "{description}".', usage) if need else None
            out.tools[index] = picked.as_dict() if picked else None
        elif (kind == "add_node" and op.get("type") == "agent") or kind == "replace_agent":
            base: dict = {}
            if kind == "replace_agent":
                node = by_id.get(_s(op.get("id"))) or {}
                base = dict(node.get("draft_agent") or existing_agents.get(_s(node.get("agent_id"))) or {})
            merged = {**base, **{k: v for k, v in op.items() if k in ("name", "role", "goal", "instructions", "backstory", "needs") and _s(v)}}
            spec = agent_spec(merged)
            needs = spec["needs"]
            tool_ids = list((base.get("config") or {}).get("tool_ids") or [])
            if needs or not tool_ids:
                chosen = await pick_agent_tools(db, user, f"{spec['role']}: {spec['goal']}\nNeeds: {needs or '(none)'}", needs, usage) if needs else []
                tool_ids = [c.tool_id for c in chosen]
            out.agents[index] = {
                "name": spec["name"], "role": spec["role"], "goal": spec["goal"], "instructions": spec["instructions"],
                "llm_provider": base.get("llm_provider", ""), "llm_model": base.get("llm_model", ""),
                "config": {**(base.get("config") or {}), "tool_ids": tool_ids},
            }
    return out


class Editor:
    def __init__(self, name: str, nodes: list[dict], edges: list[dict], config: dict, resolved: Resolved):
        self.name = name
        self.nodes = copy.deepcopy(nodes)
        self.edges = copy.deepcopy(edges)
        self.config = copy.deepcopy(config or {})
        self.resolved = resolved
        self.aliases: dict[str, str] = {}
        self.used = {n["id"] for n in self.nodes} | {e["id"] for e in self.edges}
        self.gone: set[str] = set()
        self.changes: list[str] = []
        self.warnings: list[str] = []
        self.new_tools: dict[str, dict] = {}

    # ── helpers ──

    def _mint(self, prefix: str) -> str:
        n = 1
        while f"{prefix}{n}" in self.used:
            n += 1
        self.used.add(f"{prefix}{n}")
        return f"{prefix}{n}"

    def node(self, ref: Any) -> dict:
        key = self.aliases.get(_s(ref), _s(ref))
        for n in self.nodes:
            if n["id"] == key:
                return n
        raise EditError(f"There is no step with id '{_s(ref)}'. Use the exact ids from the current workflow.")

    def label(self, n: dict) -> str:
        if n["type"] == "agent":
            name = (n.get("draft_agent") or {}).get("name") or n.get("label")
            return f'agent "{name}"' if name else f"agent step {n['id']}"
        return n.get("label") or ("the input" if n["type"] in TRIGGER_TYPES else f"{n['type'].replace('_', ' ')} step {n['id']}")

    def _edge(self, source: str, target: str, condition: str | None = None) -> None:
        if source == target or any(e["source"] == source and e["target"] == target for e in self.edges):
            return
        edge = {"id": self._mint("e"), "source": source, "target": target}
        if condition:
            edge["condition"] = condition
        self.edges.append(edge)

    def _between(self, source: str, target: str) -> list[dict]:
        return [e for e in self.edges if e["source"] == source and e["target"] == target]

    def _place(self, node: dict, after: dict | None, before: dict | None, condition: str | None) -> str:
        if before and before["type"] in TRIGGER_TYPES:
            raise EditError("Nothing can come before the workflow's trigger.")
        if after and after["type"] == "output":
            raise EditError("The output step ends the workflow; nothing can come after it.")
        if after and before:
            old = self._between(after["id"], before["id"])
            inherited = (old[0].get("condition") if old else None) or condition
            self.edges = [e for e in self.edges if e not in old]
            self._edge(after["id"], node["id"], inherited)
            self._edge(node["id"], before["id"])
            return f" between {self.label(after)} and {self.label(before)}"
        if before:
            for e in [e for e in self.edges if e["target"] == before["id"]]:
                e["target"] = node["id"]
            self._edge(node["id"], before["id"])
            return f" before {self.label(before)}"
        if after:
            if after["type"] == "condition":
                self._edge(after["id"], node["id"], condition)  # a new branch, existing branches untouched
                return f" as a new branch of {self.label(after)}"
            for e in [e for e in self.edges if e["source"] == after["id"]]:
                e["source"] = node["id"]
            self._edge(after["id"], node["id"])
            return f" after {self.label(after)}"
        return " (not connected yet — connect it or say where it goes)"

    def _detach(self, node: dict) -> None:
        incoming = [e for e in self.edges if e["target"] == node["id"]]
        outgoing = [e for e in self.edges if e["source"] == node["id"]]
        self.edges = [e for e in self.edges if e not in incoming and e not in outgoing]
        if node["type"] != "condition":  # a condition's labelled branches can't be bridged blindly
            for i in incoming:
                for o in outgoing:
                    self._edge(i["source"], o["target"], i.get("condition"))

    # ── operations ──

    def add_node(self, index: int, op: dict) -> None:
        ntype = "tool" if _s(op.get("type")) == "notification" else _s(op.get("type"))
        if ntype not in ADDABLE:
            raise EditError(f"Can't add a step of type '{ntype}'. One of: {', '.join(sorted(ADDABLE))}.")
        if len(self.nodes) >= MAX_EDIT_NODES:
            raise EditError(f"A workflow can have at most {MAX_EDIT_NODES} steps.")
        node: dict = {"id": self._mint("n"), "type": ntype}
        if _s(op.get("id")):
            self.aliases[_s(op["id"])] = node["id"]
        if ntype == "agent":
            node["draft_agent"] = self.resolved.agents[index]
            node["label"] = node["draft_agent"]["name"]
        elif ntype == "tool":
            node["need"] = _s(op.get("need") or op.get("label") or op.get("name"))[:500]
            if not node["need"]:
                raise EditError('A new tool step needs a "need": what it should do.')
            node["label"] = _s(op.get("label")) or None
            picked = self.resolved.tools.get(index)
            if picked:
                node["tool_id"] = picked["tool_id"]
                self.new_tools[node["id"]] = picked
            else:
                self.warnings.append(f'No available tool can "{node["need"]}" yet — connect a system that can, then pick its tool.')
        elif ntype == "human_approval":
            node["approval_message"] = _s(op.get("approval_message")) or "Approve this before the workflow continues?"
        for key in _NODE_FIELDS & set(op):
            if key != "label" and op[key] is not None:
                node[key] = op[key]
        self.nodes.append({k: v for k, v in node.items() if v is not None})
        after = self.node(op["after"]) if _s(op.get("after")) else None
        before = self.node(op["before"]) if _s(op.get("before")) else None
        where = self._place(self.nodes[-1], after, before, _s(op.get("condition")) or None)
        self.changes.append(f"Added {self.label(self.nodes[-1])}{where}")

    def remove_node(self, index: int, op: dict) -> None:
        node = self.node(op.get("id"))
        if node["type"] in TRIGGER_TYPES:
            raise EditError("The workflow's trigger can't be removed (replace_trigger changes it).")
        self._detach(node)
        self.nodes.remove(node)
        self.gone.add(node["id"])
        self.changes.append(f"Removed {self.label(node)}")

    def move_node(self, index: int, op: dict) -> None:
        node = self.node(op.get("id"))
        if node["type"] in TRIGGER_TYPES:
            raise EditError("The workflow's trigger can't be moved.")
        after = self.node(op["after"]) if _s(op.get("after")) else None
        before = self.node(op["before"]) if _s(op.get("before")) else None
        if not after and not before:
            raise EditError("move_node needs an \"after\" and/or \"before\" step.")
        self._detach(node)
        self.changes.append(f"Moved {self.label(node)}{self._place(node, after, before, None)}")

    def update_node(self, index: int, op: dict) -> None:
        node = self.node(op.get("id"))
        changed = []
        for key in _NODE_FIELDS & set(op):
            if op[key] is None:
                node.pop(key, None)
            elif key in ("output_config", "condition_config", "config_overrides") and isinstance(op[key], dict):
                merged = {**(node.get(key) or {}), **op[key]}
                node[key] = {k: v for k, v in merged.items() if v is not None}
            else:
                node[key] = op[key]
            changed.append(key)
        if not changed:
            raise EditError(f"update_node on {node['id']} changes nothing it can change.")
        self.changes.append(f"Updated {self.label(node)} ({', '.join(changed)})")

    def replace_agent(self, index: int, op: dict) -> None:
        node = self.node(op.get("id"))
        if node["type"] != "agent":
            raise EditError(f"Step {node['id']} isn't an agent step.")
        node["draft_agent"] = self.resolved.agents[index]
        node["label"] = node["draft_agent"]["name"]
        self.changes.append(f"Rewrote {self.label(node)}")

    def set_tool(self, index: int, op: dict) -> None:
        node = self.node(op.get("id"))
        if node["type"] != "tool":
            raise EditError(f"Step {node['id']} isn't a tool step.")
        node["need"] = _s(op.get("need"))[:500]
        picked = self.resolved.tools.get(index)
        node.pop("tool_args", None)
        if picked:
            node["tool_id"] = picked["tool_id"]
            self.new_tools[node["id"]] = picked
        else:
            node.pop("tool_id", None)
            self.warnings.append(f'No available tool can "{node["need"]}" yet — connect a system that can, then pick its tool.')
        self.changes.append(f"Changed what {self.label(node)} does")

    def add_edge(self, index: int, op: dict) -> None:
        if any(self.aliases.get(_s(op.get(k)), _s(op.get(k))) in self.gone for k in ("source", "target")):
            return
        source, target = self.node(op.get("source")), self.node(op.get("target"))
        condition = _s(op.get("condition")) or None
        if condition and source["type"] != "condition":
            condition = None
        self._edge(source["id"], target["id"], condition)
        self.changes.append(f"Connected {self.label(source)} to {self.label(target)}")

    def remove_edge(self, index: int, op: dict) -> None:
        if any(self.aliases.get(_s(op.get(k)), _s(op.get(k))) in self.gone for k in ("source", "target")):
            return
        source, target = self.node(op.get("source")), self.node(op.get("target"))
        before = len(self.edges)
        self.edges = [e for e in self.edges if not (e["source"] == source["id"] and e["target"] == target["id"])]
        if len(self.edges) == before:
            raise EditError(f"{self.label(source)} isn't connected to {self.label(target)}.")
        self.changes.append(f"Disconnected {self.label(source)} from {self.label(target)}")

    def update_edge(self, index: int, op: dict) -> None:
        source, target = self.node(op.get("source")), self.node(op.get("target"))
        edges = self._between(source["id"], target["id"])
        if not edges:
            raise EditError(f"{self.label(source)} isn't connected to {self.label(target)}.")
        for e in edges:
            if _s(op.get("condition")):
                e["condition"] = _s(op["condition"])[:200]
            else:
                e.pop("condition", None)
        self.changes.append(f"Relabelled the line from {self.label(source)} to {self.label(target)}")

    def replace_trigger(self, index: int, op: dict) -> None:
        ntype = _s(op.get("type"))
        if ntype not in TRIGGER_TYPES:
            raise EditError("replace_trigger type must be input, manual_trigger or schedule_trigger.")
        trigger = next((n for n in self.nodes if n["type"] in TRIGGER_TYPES), None)
        if trigger is None:
            raise EditError("This workflow has no trigger to replace.")
        if trigger["type"] != ntype:
            replacement = {"id": trigger["id"], "type": ntype, "position": trigger.get("position")}
            self.nodes[self.nodes.index(trigger)] = {k: v for k, v in replacement.items() if v is not None}
            self.changes.append(f"The workflow now starts with a {ntype.replace('_', ' ')}")

    def rename_workflow(self, index: int, op: dict) -> None:
        name = _s(op.get("name"))
        if not 1 <= len(name) <= 120:
            raise EditError("The new name must be 1-120 characters.")
        self.name = name
        self.changes.append(f'Renamed the workflow to "{name}"')

    def set_config(self, index: int, op: dict) -> None:
        values = op.get("config")
        if not isinstance(values, dict):
            raise EditError('set_config needs a "config" object.')
        merged = {**self.config}
        for key, value in values.items():
            if value is None:
                merged.pop(key, None)
            elif key == "approvals" and isinstance(value, dict):
                merged["approvals"] = {**(merged.get("approvals") or {}), **value}
            else:
                merged[key] = value
        if values.get("node_retry_count") and "on_node_failure" not in values:
            merged["on_node_failure"] = "retry"  # retries only apply under that policy
        try:
            self.config = WorkflowConfig.model_validate(merged).model_dump()
        except Exception as exc:  # pydantic ValidationError
            raise EditError(f"Those settings aren't valid: {exc}") from exc
        self.changes.append(f"Changed settings: {', '.join(values)}")

    # ── run ──

    def apply(self, ops: list) -> None:
        handlers = {
            "add_node": self.add_node, "remove_node": self.remove_node, "move_node": self.move_node,
            "update_node": self.update_node, "replace_agent": self.replace_agent, "set_tool": self.set_tool,
            "add_edge": self.add_edge, "remove_edge": self.remove_edge, "update_edge": self.update_edge,
            "replace_trigger": self.replace_trigger, "rename_workflow": self.rename_workflow, "set_config": self.set_config,
        }
        for index, op in enumerate(ops):
            if not isinstance(op, dict) or op.get("op") not in handlers:
                raise EditError(f"Operation {index + 1} isn't one of: {', '.join(handlers)}.")
            handlers[op["op"]](index, op)


__all__ = ["EditError", "Editor", "Resolved", "resolve"]
