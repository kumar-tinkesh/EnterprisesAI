"""AI Compiler — stages 3 & 4 of the catalog pipeline.

Stage 1 (access filtering) and stage 2 (semantic matching) live in
:mod:`vendor_resources.services.catalog_engine` and are reused here. This
module:

  * **Schema shrinking** — trims verbose ``description``/``$comment`` keys from
    a tool's ``parameters_schema`` to save LLM tokens.
  * **Structured spec generation** — renders the ``AGENT_COMPILER`` prompt with
    the access-filtered + semantically-ranked candidate tools, asks the gateway
    for JSON (``response_format={"type": "json_object"}``), and validates the
    output into a :class:`CompiledAgentSpec`.

Compile is robust: every bound ``tool_id`` is checked against the authorized
candidate set (defense-in-depth), a single retry is attempted on parse failure,
and a linear fallback spec is produced if the LLM can't be satisfied. It never
raises on LLM misbehaviour.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from apps.llm_gateway.prompts import PromptRegistry, PromptType
from apps.llm_gateway.types import CompletionRequest, Message, Role

from src.api.deps import CurrentUser
from sqlalchemy.ext.asyncio import AsyncSession

from vendor_resources.schemas import AgentNode, CompiledAgentSpec
from vendor_resources.services.catalog_engine import get_authorized_vendor_catalog_semantic
from vendor_resources.services import embeddings

logger = logging.getLogger("vendor_resources.compiler")

# Keys stripped from JSON schemas (recursively) to shrink prompt token count.
_VERBOSE_KEYS = {"description", "$comment", "title", "examples"}


def shrink_schema(params: dict[str, Any]) -> dict[str, Any]:
    """Return a token-leaner copy of a JSON schema.

    Drops verbose keys (``description``/``$comment``/``title``/``examples``)
    from every nested object while preserving the structural shape (types,
    properties, required). The top level is returned as-is structurally minus
    those keys.
    """
    if not isinstance(params, dict):
        return params

    def _clean(node: Any) -> Any:
        if isinstance(node, dict):
            cleaned: dict[str, Any] = {}
            for k, v in node.items():
                if k in _VERBOSE_KEYS:
                    continue
                cleaned[k] = _clean(v)
            return cleaned
        if isinstance(node, list):
            return [_clean(item) for item in node]
        return node

    return _clean(params)


def _build_catalog(candidates: list) -> list[dict[str, Any]]:
    """Build the compact tool catalog passed to the compiler prompt."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "method": t.method,
            "parameters_schema": shrink_schema(t.parameters_schema or {}),
        }
        for t in candidates
    ]


def _fallback_spec(query: str, candidates: list) -> CompiledAgentSpec:
    """Linear fallback spec over the top candidate (used when LLM compile fails)."""
    if not candidates:
        return CompiledAgentSpec(agent_name="empty_agent", description="No authorized tools available.")
    top = candidates[0]
    node = AgentNode(
        id="n1",
        node_type="tool.call",
        tool_id=top.id,
        args={},
        description=f"Call {top.name} for: {query}",
    )
    return CompiledAgentSpec(
        agent_name="fallback_agent",
        description=f"Fallback plan for: {query}",
        nodes=[node],
        edges=[],
    )


def _validate_tool_ids(spec: CompiledAgentSpec, allowed: set[str]) -> CompiledAgentSpec:
    """Enforce that every bound ``tool_id`` is in the authorized set.

    Offending nodes are neutralised (``tool_id=None``, ``unconfigured=True``)
    rather than dropped, so the spec stays executable (as a simulation).
    """
    for node in spec.nodes:
        if node.tool_id is not None and node.tool_id not in allowed:
            logger.warning("compiler bound disallowed tool_id %s; neutralising node %s", node.tool_id, node.id)
            node.tool_id = None
            node.unconfigured = True
    return spec


def _parse_spec(content: str | None) -> CompiledAgentSpec | None:
    """Parse LLM JSON output into a ``CompiledAgentSpec``; None on any failure."""
    if not content:
        return None
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("compiler JSON parse failed: %s", exc)
        return None
    try:
        return CompiledAgentSpec.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        logger.warning("compiler spec validation failed: %s", exc)
        return None


async def compile_agent(
    db: AsyncSession, *, user: CurrentUser, query: str, top_k: int = 5
) -> CompiledAgentSpec:
    """Compile a natural-language ``query`` into a validated ``CompiledAgentSpec``.

    Pipeline: access-filtered + semantic catalog → schema shrink → AGENT_COMPILER
    prompt → gateway JSON completion → Pydantic validation (with tool_id authz
    check, one retry, and a linear fallback). Never raises on LLM misbehaviour.
    """
    candidates = await get_authorized_vendor_catalog_semantic(
        db, user=user, query=query, top_k=top_k
    )
    if not candidates:
        return _fallback_spec(query, candidates)

    allowed = {t.id for t in candidates}
    catalog = _build_catalog(candidates)

    try:
        prompt = PromptRegistry.format(
            PromptType.AGENT_COMPILER, nl_request=query, available_tools=catalog
        )
    except KeyError as exc:
        logger.error("compiler prompt render failed: %s", exc)
        return _fallback_spec(query, candidates)

    request = CompletionRequest(
        messages=[Message(role=Role.SYSTEM, content=prompt), Message(role=Role.USER, content=query)],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    async def _attempt(extra: str | None = None) -> CompiledAgentSpec | None:
        req = request
        if extra:
            req = CompletionRequest(
                messages=[
                    Message(role=Role.SYSTEM, content=prompt),
                    Message(role=Role.USER, content=query),
                    Message(role=Role.SYSTEM, content=f"Previous output was invalid: {extra}. Output ONLY valid JSON matching the schema."),
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        try:
            gw = embeddings.get_gateway()
            resp = await gw.complete(req)
        except Exception as exc:  # provider unavailable / not configured
            logger.warning("compiler LLM call failed: %s", exc)
            return None
        spec = _parse_spec(resp.content)
        if spec is None:
            return None
        return _validate_tool_ids(spec, allowed)

    spec = await _attempt()
    if spec is not None:
        return spec

    # One retry with the failure reason appended.
    spec = await _attempt(extra="invalid JSON or schema")
    if spec is not None:
        return spec

    logger.warning("compiler falling back to linear spec for query: %s", query)
    return _fallback_spec(query, candidates)


__all__ = ["compile_agent", "shrink_schema"]