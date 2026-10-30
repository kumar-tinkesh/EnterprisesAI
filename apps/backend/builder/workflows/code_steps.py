"""Code steps: fixed logic a workflow runs between its AI steps – no model call, so fast and the same every time.

A ``code`` node names one registered function (``node["code"]``). It gets its sources' texts and the steps it leads
to, and answers with its output – plus, when it splits work, the text each next step gets instead (``routed``,
e.g. one batch of jobs per scoring agent). Functions are registered by the templates that use them; a workflow can
only name one that exists (``builder.graph.validation``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class CodeInput:
    # (source step's label, its text), as an agent step would get them.
    parts: list[tuple[str, str]]
    # What the run was asked.
    request: str
    # (node id, node type) of each step this one leads to.
    targets: list[tuple[str, str]]


@dataclass
class CodeResult:
    output: str
    routed: dict[str, str] = field(default_factory=dict)


CodeFn = Callable[[CodeInput], CodeResult]
_REGISTRY: dict[str, CodeFn] = {}


def register(name: str) -> Callable[[CodeFn], CodeFn]:
    def wrap(fn: CodeFn) -> CodeFn:
        _REGISTRY[name] = fn
        return fn
    return wrap


def code_step(name: str | None) -> CodeFn | None:
    import builder.templates  # noqa: F401  (the templates register their code steps)

    return _REGISTRY.get(name or "")


__all__ = ["CodeInput", "CodeResult", "code_step", "register"]
