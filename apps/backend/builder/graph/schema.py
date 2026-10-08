"""The workflow graph format: nodes, edges and whole-run settings.

Shapes follow the AI Marketplace's ``schemas/workflows/graph.py`` so its canvas
can be ported as is, minus its legacy ``notification`` node (merged into
``tool`` there too). Unknown keys a canvas sends (``data``, ``selected``, …)
are dropped; what's stored is ``model_dump(exclude_none=True)``.

Tools are referenced as ``mcp:<server_id>:<tool_name>`` everywhere (a tool
node's ``tool_id``, an agent's ``config.tool_ids``).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal[
    "input",
    "manual_trigger",
    "schedule_trigger",
    "agent",
    "tool",
    "condition",
    "join",
    "human_approval",
    "output",
]
TRIGGER_TYPES = frozenset({"input", "manual_trigger", "schedule_trigger"})
NODE_TYPES = frozenset(NodeType.__args__)


class Position(BaseModel):
    x: float = 0
    y: float = 0


class InputVariable(BaseModel):
    """A value the person starting the run fills in (``input`` node)."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    label: str | None = Field(default=None, max_length=120)
    type: Literal["text", "number", "boolean", "json"] = "text"
    required: bool = False
    description: str | None = Field(default=None, max_length=500)


class JoinPolicy(BaseModel):
    mode: Literal["all", "any", "count"] = "all"
    min_required: int | None = Field(default=None, ge=1)


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=5)


class DraftAgent(BaseModel):
    """An agent step's agent that isn't saved yet (drafted by the assistant or
    added on the canvas). Saving the workflow creates it as one of the
    workflow's own agents and replaces this with ``agent_id``."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(default="", max_length=20_000)
    llm_provider: str = Field(default="", max_length=50)
    llm_model: str = Field(default="", max_length=100)
    # Validated as builder.agents.config.AgentConfig where it's used.
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=255)
    type: NodeType
    position: Position = Field(default_factory=Position)
    label: str | None = Field(default=None, max_length=200)
    retry: RetryPolicy | None = None

    # input
    variables: list[InputVariable] | None = None
    # agent: a standalone agent or one of this workflow's own; overrides merge over its config here only.
    agent_id: str | None = None
    draft_agent: DraftAgent | None = None
    config_overrides: dict[str, Any] | None = None
    # tool: which tool, plus fixed arguments that always win over inferred ones.
    tool_id: str | None = None
    # What the step is for, in words ("send the summary to #sales") — kept so a
    # missing tool can be found again once its system is connected.
    need: str | None = Field(default=None, max_length=500)
    tool_args: dict[str, Any] | None = None
    message_template: str | None = Field(default=None, max_length=20_000)
    # condition (builder.graph.condition_rules)
    condition_config: dict[str, Any] | None = None
    # join
    join_policy: JoinPolicy | None = None
    # human_approval
    approval_message: str | None = Field(default=None, max_length=2000)
    # output (builder.graph.output_config)
    output_config: dict[str, Any] | None = None
    # schedule_trigger: cron expression + timezone (the scheduler lands later).
    schedule: dict[str, Any] | None = None


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=255)
    source: str
    target: str
    # A condition node's branch label ("Approved", "Needs edits", …).
    condition: str | None = Field(default=None, max_length=200)


class ToolApprovalPolicy(BaseModel):
    """Ask a person before a tool of this risk runs."""

    read: bool = False
    edit: bool = True
    delete: bool = True


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_run_seconds: int = Field(default=1800, ge=30, le=86_400)
    # Guards a condition loop that never exits.
    max_steps: int = Field(default=50, ge=1, le=500)
    on_node_failure: Literal["abort", "skip", "retry"] = "abort"
    node_retry_count: int = Field(default=0, ge=0, le=5)
    default_knowledge_base_ids: list[str] = Field(default_factory=list, max_length=10)
    approvals: ToolApprovalPolicy = Field(default_factory=ToolApprovalPolicy)


def parse_tool_id(tool_id: str | None) -> tuple[str, str] | None:
    """``mcp:<server_id>:<tool_name>`` -> (server_id, tool_name), else None."""
    if not isinstance(tool_id, str):
        return None
    prefix, _, rest = tool_id.partition(":")
    server_id, _, tool_name = rest.partition(":")
    if prefix != "mcp" or not server_id or not tool_name:
        return None
    return server_id, tool_name


def make_tool_id(server_id: str, tool_name: str) -> str:
    return f"mcp:{server_id}:{tool_name}"


__all__ = [
    "NodeType",
    "NODE_TYPES",
    "TRIGGER_TYPES",
    "Position",
    "InputVariable",
    "DraftAgent",
    "JoinPolicy",
    "RetryPolicy",
    "WorkflowNode",
    "WorkflowEdge",
    "ToolApprovalPolicy",
    "WorkflowConfig",
    "parse_tool_id",
    "make_tool_id",
]
