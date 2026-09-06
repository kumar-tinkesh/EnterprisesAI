"""Semantic embedding for MCP servers/tools (vendor write-path).

``embed_text`` is the low-level "text -> vector via the LLM gateway" call —
pure and side-effect-free (no DB access, no mutation). ``user.services.
catalog_engine`` is allowed to reuse it to embed a *query* at search time;
this is a narrow, documented exception to the "user never imports
vendor.services" rule (see the repo's import-linter contracts) — it holds
no vendor business logic, just an outbound gateway call.

``embed_server``/``embed_tool`` mutate a ``VendorMCPServer``/``MCPTool``
ORM instance in place and are only ever called from vendor's own add/verify
flow (``vendor.services.mcp_service``) — never from ``user``.
"""
from __future__ import annotations

from typing import Optional

from vendor.models import MCPTool, VendorMCPServer
from vendor.services.text_repr import server_text, tool_text


async def embed_text(
    text: str, *, provider: Optional[str] = None, model: Optional[str] = None
) -> Optional[tuple[list[float], str]]:
    """Embed ``text`` via the gateway. Returns ``(vector, model)`` or ``None``."""
    if not text:
        return None
    try:
        from apps.llm_gateway.exceptions import LLMGatewayError
        from apps.llm_gateway.types import EmbeddingResponse

        from vendor.services.llm_gateway_client import get_gateway

        resp: EmbeddingResponse = await get_gateway().embed(
            [text], provider=provider, model=model
        )
    except LLMGatewayError:
        return None
    except Exception:
        return None

    if not resp.embeddings:
        return None
    return list(resp.embeddings[0]), resp.model or (model or "")


async def embed_server(
    server: VendorMCPServer, *, provider: Optional[str] = None
) -> bool:
    """(Re)compute ``server.embedding``/``embedding_model``/``dim`` in place.

    Returns False (leaving the server's embedding fields untouched) when no
    embedding could be produced right now (provider not configured, network
    error, …) — callers should treat that as "skip for now", not a fatal
    error for the surrounding add/verify operation.
    """
    embedded = await embed_text(server_text(server), provider=provider)
    if embedded is None:
        return False
    vector, model = embedded
    server.embedding = vector
    server.embedding_model = model
    server.dim = len(vector)
    return True


async def embed_tool(tool: MCPTool, *, provider: Optional[str] = None) -> bool:
    """(Re)compute ``tool.embedding``/``embedding_model``/``dim`` in place.

    The embedded text includes the tool's input parameter names so a query
    like "resize an image" can match a tool whose description is thin but
    whose schema has a ``width``/``height`` property. See :func:`embed_server`
    for the "no embedding available" contract.
    """
    embedded = await embed_text(tool_text(tool), provider=provider)
    if embedded is None:
        return False
    vector, model = embedded
    tool.embedding = vector
    tool.embedding_model = model
    tool.dim = len(vector)
    return True


__all__ = ["embed_text", "embed_server", "embed_tool"]
