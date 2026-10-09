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
    # Set when a schedule started it (NULL = a person did).
    schedule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    # "run" (a person or a schedule) | "test" (a test case: data-changing tool
    # calls are simulated, approval steps pass on their own — see builder.quality).
    purpose: Mapped[str] = mapped_column(String(20), default="run", server_default="run", index=True)
    # Started through the public API with this publishable key (purpose "public").
    public_key_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


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


class BuilderSchedule(Base, TimestampMixin):
    """Run an agent or a workflow automatically, on a cron schedule.

    A workflow's schedule comes from its Schedule trigger step (kept in sync on
    every save, keyed by ``node_id``); an agent's is made directly. Either way
    it runs as ``owner_id`` with *their* connected tools, exactly like a run
    they started — and is checked the same way first: if it can't run (a tool
    got disconnected, a required input is empty) that occurrence is skipped
    and ``last_error`` says why, instead of a run that fails half-way.

    Fired by every worker's schedule loop; a conditional update on
    ``next_run_at`` makes sure each occurrence starts exactly one run however
    many workers see it. ``next_run_at`` is UTC, recomputed from the cron in
    the schedule's own timezone each time (DST-correct). NULL = paused.
    """

    __tablename__ = "builder_schedules"
    __table_args__ = (
        Index("ix_builder_schedules_due", "enabled", "next_run_at"),
        UniqueConstraint("workflow_id", "node_id", name="uq_builder_schedule_workflow_node"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # agent | workflow
    agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # The workflow's Schedule trigger step this row mirrors (NULL for agents).
    node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cron: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # What each run is asked: {"text": "...", "variables": {...}}.
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # started | skipped | error
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BuilderVersion(Base, TimestampMixin):
    """A saved version of an agent or a workflow: the full definition as it
    was right after that save, so any earlier state can be looked at again or
    brought back.

    One row per save (``version`` = the definition's version number after
    it). A restore is itself a new save, so history only ever grows forward.
    A workflow's snapshot also carries the workflow's own agents (the ones its
    steps created), since restoring the graph without them would point at
    agents that may since have been changed or removed; shared standalone
    agents keep their own history.
    """

    __tablename__ = "builder_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_builder_version_agent"),
        UniqueConstraint("workflow_id", "version", name="uq_builder_version_workflow"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # agent | workflow
    agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    # agent: name, role, goal, instructions, llm_provider, llm_model, config.
    # workflow: name, description, nodes, edges, config, agents {id: agent fields}.
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    # Why it exists ("Created", "Saved", "Restored from v3") and what changed
    # since the version before it, in words.
    note: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class BuilderTestCase(Base, TimestampMixin):
    """One test of an agent or workflow: what it's asked, and what a good
    response does (a behaviour to look for, not an exact answer)."""

    __tablename__ = "builder_test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    input: Mapped[str] = mapped_column(Text)
    # A workflow's input fields, by name.
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    expectation: Mapped[str] = mapped_column(Text)
    # normal | ambiguous | knowledge_gap | tools | safety | injection | out_of_scope
    category: Mapped[str] = mapped_column(String(30), default="normal")
    # manual | generated
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class BuilderTestRun(Base, TimestampMixin):
    """Running a set of test cases against one version of an agent/workflow.

    Each case is a real run (``BuilderRun.purpose == "test"``) through the same
    worker, graded by a model judge when it finishes; the score is the mean of
    the case scores, also broken down by what each category tests.
    """

    __tablename__ = "builder_test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # agent | workflow
    agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    # running | done | cancelled
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-100
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    # {"behaviour": 80, "safety": 100, ...}
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    judge_tokens: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BuilderTestResult(Base, TimestampMixin):
    """One case within a test run: its run, and the judge's verdict on it.
    The case's text is copied in, so results survive the case being edited."""

    __tablename__ = "builder_test_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("builder_test_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(30))
    input: Mapped[str] = mapped_column(Text)
    expectation: Mapped[str] = mapped_column(Text)
    # running | passed | failed | error (it couldn't run at all)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    score: Mapped[Optional[float]] = mapped_column(nullable=True)  # 0-1
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BuilderPublicKey(Base, TimestampMixin):
    """A publishable key: lets apps and websites run ONE agent or workflow
    through the public API (``/api/v1/public``) without a login.

    Runs as the person who created the key, with *their* connected tools —
    data-changing calls still wait for their approval unless they turned that
    off — so publishing is theirs to decide (creator or tenant admin, and an
    explicit yes when write tools are exposed). Only a SHA-256 hash of the
    key is stored; the key itself is shown once, at creation.

    ``version`` pins a saved version (later edits don't change what callers
    get until the key is moved to a newer one); NULL = the latest saved.
    """

    __tablename__ = "builder_public_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # agent | workflow
    agent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("builder_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # "eai_pk_ab12" — enough to recognise a key in a list, useless for calling.
    key_prefix: Mapped[str] = mapped_column(String(20))
    # active | paused | revoked
    status: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Browser origins allowed to use it ("https://acme.com"); empty = any (server-to-server too).
    allowed_origins: Mapped[list] = mapped_column(JSON, default=list)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=20)
    daily_quota: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "BuilderPublicKey",
    "BuilderTestCase",
    "BuilderTestRun",
    "BuilderTestResult",
    "BuilderVersion",
    "BuilderSchedule",
    "BuilderWorkflow",
    "BuilderAgent",
    "BuilderRun",
    "BuilderNodeRun",
    "BuilderToolCall",
    "BuilderApproval",
]
