"""Vendor Tool invocation — the runtime that executes a bound tool node.

For tools with a real ``endpoint_url`` the call is made via ``httpx`` (method +
JSON args). For tools without an endpoint (e.g. the seeded defaults, which have
``endpoint_url=None``) a **simulated** result is returned so a compiled agent
DAG runs end-to-end without any external API — this keeps the executor
demonstrable and the tests network-free.

``vault_secret_ref`` injection (auth headers from the vault) is intentionally
deferred: no tool sets it yet. Add when a real tool needs authenticated calls.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from vendor_resources.schemas import AgentNode
from vendor_resources.services.tool_service import get_tool

logger = logging.getLogger("vendor_resources.tool_executor")

_HTTP_TIMEOUT = 30.0


async def invoke_tool(db: AsyncSession, node: AgentNode, state: dict[str, Any]) -> dict[str, Any]:
    """Execute a single agent node's bound tool.

    Returns a result dict written into the agent state under ``node.id``. Never
    raises — failures are returned as structured error dicts so the DAG keeps
    running.
    """
    if node.tool_id is None or node.unconfigured:
        return {
            "simulated": True,
            "node": node.id,
            "message": "no tool bound (unconfigured)",
        }

    tool = await get_tool(db, node.tool_id)
    if tool is None:
        return {"simulated": True, "node": node.id, "message": "tool not found"}

    if not tool.endpoint_url:
        # No real endpoint → simulate so the DAG completes without network.
        return {
            "simulated": True,
            "node": node.id,
            "tool": tool.name,
            "method": tool.method,
            "args": node.args,
            "message": "no endpoint configured (simulated)",
        }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.request(
                tool.method,
                tool.endpoint_url,
                json=node.args,
            )
        try:
            body: Any = resp.json()
        except ValueError:
            body = {"text": resp.text}
        return {
            "simulated": False,
            "node": node.id,
            "tool": tool.name,
            "status": resp.status_code,
            "body": body,
        }
    except Exception as exc:
        logger.warning("tool %s (%s) call failed: %s", tool.name, node.id, exc)
        return {
            "simulated": False,
            "node": node.id,
            "tool": tool.name,
            "error": str(exc),
        }


__all__ = ["invoke_tool"]