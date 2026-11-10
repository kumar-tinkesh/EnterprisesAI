"""Code steps: fixed logic a workflow runs between its AI steps – no model call, so fast and the same every time.

A ``code`` node names one registered function (``node["code"]``). It gets its sources' texts and the steps it leads
to, and answers with its output – plus, when it splits work, the text each next step gets instead (``routed``,
e.g. one batch of jobs per scoring agent). Functions are registered by the templates that use them; a workflow can
only name one that exists (``builder.graph.validation``).

A code node may also name ``tool_needs`` (the same shape as an agent's): then its function is ``async`` and calls
those systems' tools itself through ``inp.tools`` – fixed calls a template knows in advance (search these job
boards, add these rows, save these drafts), with no AI deciding them. Every call goes through the run's ledger
(``builder.runs.tool_calls``): it is recorded, asks first when the workflow's approvals say so (a send always
does), and a resumed step gets the recorded answer instead of calling again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol, Union


@dataclass
class ToolAnswer:
    """What a tool call answered: its text, its structured content when it has one, and whether it failed."""

    text: str
    structured: dict | None = None
    is_error: bool = False
    # A person said no (a send they chose not to make, a save they didn't want).
    declined: bool = False
    # What it ran with – a person may have changed it when they said yes (e.g. a send's recipient).
    arguments: dict | None = None


class StepTools(Protocol):
    def has(self, system: str, tool: str | None = None) -> bool:
        """Is this system (and this tool of it) connected for the person running the workflow?"""

    async def call(self, system: str, tool: str, arguments: dict, *, key: str, timeout: float = 60,
                   ask: bool | None = None, note: str = "") -> ToolAnswer:
        """Run one tool. ``key`` names the call within the step, the same on every attempt ("search:1"), so a
        resumed step reuses its answer. ``ask`` True / False overrides the workflow's approval rule for this call
        (a send still always asks); ``note`` is added to what the person is asked ("the number is from your
        resume"). An unknown system or tool answers ``is_error``."""


@dataclass
class CodeInput:
    # (source step's label, its text), as an agent step would get them.
    parts: list[tuple[str, str]]
    # What the run was asked.
    request: str
    # (node id, node type) of each step this one leads to.
    targets: list[tuple[str, str]]
    # The node's tool_needs, ready to call (None when it names none).
    tools: StepTools | None = None
    # Live "▸ " notes for the person watching the run.
    note: Callable[[str], Awaitable[None]] | None = None


@dataclass
class CodeResult:
    output: str
    routed: dict[str, str] = field(default_factory=dict)


CodeFn = Callable[[CodeInput], Union[CodeResult, Awaitable[CodeResult]]]
_REGISTRY: dict[str, CodeFn] = {}


def register(name: str) -> Callable[[CodeFn], CodeFn]:
    def wrap(fn: CodeFn) -> CodeFn:
        _REGISTRY[name] = fn
        return fn
    return wrap


def code_step(name: str | None) -> CodeFn | None:
    import builder.templates  # noqa: F401  (the templates register their code steps)

    return _REGISTRY.get(name or "")


__all__ = ["CodeInput", "CodeResult", "StepTools", "ToolAnswer", "code_step", "register"]
