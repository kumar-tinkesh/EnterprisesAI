"""Request/response schemas for agents and workflows."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from builder.agents.config import AgentConfig
from builder.graph.schema import WorkflowConfig, WorkflowEdge, WorkflowNode


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=4000)
    instructions: str = Field(default="", max_length=20_000)
    llm_provider: str = Field(default="", max_length=50)
    llm_model: str = Field(default="", max_length=100)
    config: AgentConfig = Field(default_factory=AgentConfig)
    # Create the agent as one of this workflow's own (deleted with it).
    workflow_id: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, min_length=1, max_length=255)
    goal: str | None = Field(default=None, min_length=1, max_length=4000)
    instructions: str | None = Field(default=None, max_length=20_000)
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=100)
    config: AgentConfig | None = None
    # The version the client last loaded; a newer saved version -> 409.
    expected_version: int | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    role: str
    goal: str
    instructions: str
    llm_provider: str
    llm_model: str
    config: dict
    workflow_id: str | None
    owner_id: str
    version: int
    can_manage: bool
    created_at: datetime
    updated_at: datetime


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=200)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=500)
    config: WorkflowConfig = Field(default_factory=WorkflowConfig)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    nodes: list[WorkflowNode] | None = Field(default=None, max_length=200)
    edges: list[WorkflowEdge] | None = Field(default=None, max_length=500)
    config: WorkflowConfig | None = None
    expected_version: int | None = None


class WorkflowValidateRequest(BaseModel):
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=200)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=500)
    config: WorkflowConfig = Field(default_factory=WorkflowConfig)
    # When validating edits to an existing workflow (its own agents are allowed).
    workflow_id: str | None = None


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    version: int
    node_count: int
    can_manage: bool
    created_at: datetime
    updated_at: datetime


class WorkflowOut(WorkflowSummary):
    nodes: list[dict]
    edges: list[dict]
    config: dict
    # This workflow's own agents.
    agents: list[AgentOut] = Field(default_factory=list)


class Problem(BaseModel):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    server_id: str | None = None


class CheckResult(BaseModel):
    ok: bool
    problems: list[Problem]
