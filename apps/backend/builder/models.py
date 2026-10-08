"""ORM models for the builder domain: agents, workflows, and their runs.

Registered on the shared ``src.db.base.Base`` metadata (like ``vendor.models``
and ``knowledge.models``). Ids are 36-char UUID strings and every structured
field is portable ``JSON``, so the schema runs on SQLite and PostgreSQL.

Sharing: agents and workflows belong to a tenant and every member can see and
run them; changing or deleting one is for its creator or a tenant admin (same
rule as knowledge bases). A run always executes as the user who started it,
with *their* connected tools.

Durability (see the Phase 3 worker): a run never reads the live agent/workflow
row after it starts. It carries a ``definition`` snapshot, its progress lives
in ``state`` + one ``BuilderNodeRun`` per node attempt, and every tool call is
recorded in ``BuilderToolCall`` *before* it is sent — so a run interrupted by a
crash resumes from its last completed step on the same graph, and a
data-changing call whose outcome is unknown is never silently re-sent.

SQLite doesn't enforce ``ON DELETE CASCADE`` by default, so the API deletes
child rows explicitly; the foreign keys still document the relationships.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, TimestampMixin
from src.models.tenant import uuid_str


class BuilderWorkflow(Base, TimestampMixin):
    """A graph of steps. ``nodes``/``edges`` are stored exactly as the canvas
    sends them (validated by ``builder.graph.validation`` on save)."""

    __tablename__ = "builder_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    # Whole-run policy (builder.graph.schema.WorkflowConfig).
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Bumped on every save that changes the graph or config; a run records
    # which version it executed.
    version: Mapped[int] = mapped_column(Integer, default=1)


class BuilderAgent(Base, TimestampMixin):
    """One autonomous agent: who it is, which model, which tools and knowledge.

    ``workflow_id`` set = the agent belongs to that workflow (created from a
    workflow step) and is deleted with it; NULL = a standalone agent.
    """

    __tablename__ = "builder_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255))
    goal: Mapped[str] = mapped_column(Text)
    # The agent's standing instructions / persona (Marketplace's "backstory").
    instructions: Mapped[str] = mapped_column(Text, default="")
    # Empty = the LLM gateway's default provider / that provider's default model.
    llm_provider: Mapped[str] = mapped_column(String(50), default="")
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    # Validated by builder.agents.config.AgentConfig: llm, tool_ids,
    # knowledge_base_ids, response, tools, reliability, approvals, guardrails.
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)


class BuilderRun(Base, TimestampMixin):
    """One execution of an agent or a workflow.

    Status: queued -> running -> (waiting -> running)* -> succeeded | failed | cancelled.
    ``waiting`` = paused on a person (an approval, or confirming a call whose
    outcome is unknown); no worker holds it while it waits.
    """

    __tablename__ = "builder_runs"
    __table_args__ = (
        Index("ix_builder_runs_status_lease", "status", "lease_expires_at"),
        Index("ix_builder_runs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    # The user the run executes as (their own tool connections).
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # agent | workflow
    # No foreign keys: run history outlives a deleted agent/workflow.
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    # Frozen copy of what runs: {"workflow": {...}, "agents": {id: {...}}} or {"agent": {...}}.
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"text": "...", "variables": {...}}
    input: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # Executor checkpoint: completed node outputs, pending frontier, loop counts.
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Worker lease: whoever holds it runs the job; an expired lease means the
    # worker died and the run may be picked up again (``attempts`` counts
    # those recoveries; resuming after an approval doesn't count).
    lease_owner: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BuilderNodeRun(Base, TimestampMixin):
    """One attempt at one node of a run. Each attempt writes only its own row,
    so parallel branches never race on a shared blob."""

    __tablename__ = "builder_node_runs"
    __table_args__ = (UniqueConstraint("run_id", "node_id", "attempt", name="uq_builder_node_run_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(ForeignKey("builder_runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(255))
    node_type: Mapped[str] = mapped_column(String(50))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    # running | succeeded | failed | skipped | waiting
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Agent nodes checkpoint their conversation here after every model turn,
    # so a crash mid-agent resumes at the last turn, not the first.
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BuilderToolCall(Base, TimestampMixin):
    """Ledger of every tool call a run makes, written *before* the call is sent.

    ``call_key`` is deterministic for the call's position in the run (node,
    attempt, agent turn, index), so a resumed run finds the call it already
    made: ``succeeded`` -> reuse the stored result; ``started`` with no
    outcome -> a read tool may run again, a data-changing one waits for a
    person to decide.
    """

    __tablename__ = "builder_tool_calls"
    __table_args__ = (UniqueConstraint("run_id", "call_key", name="uq_builder_tool_call_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(ForeignKey("builder_runs.id", ondelete="CASCADE"), index=True)
    node_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    call_key: Mapped[str] = mapped_column(String(255))
    server_id: Mapped[str] = mapped_column(String(36))
    tool_name: Mapped[str] = mapped_column(String(255))
    risk: Mapped[str] = mapped_column(String(10))  # read | edit | delete
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    # started | succeeded | failed | unknown
    status: Mapped[str] = mapped_column(String(20), default="started")
    result_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_error: Mapped[Optional[bool]] = mapped_column(nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BuilderApproval(Base, TimestampMixin):
    """A decision a run is waiting on.

    kind: ``tool_call`` (a data-changing call needs a yes), ``human_step`` (a
    workflow's approval step), ``uncertain_call`` (a data-changing call may
    already have run before a crash — run it again?).
    """

    __tablename__ = "builder_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(ForeignKey("builder_runs.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    risk: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # What the person is shown: tool arguments, or a workflow step's message and current text.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # pending | approved | rejected | edited | expired
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    edited_input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "BuilderWorkflow",
    "BuilderAgent",
    "BuilderRun",
    "BuilderNodeRun",
    "BuilderToolCall",
    "BuilderApproval",
]
