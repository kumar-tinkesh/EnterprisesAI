"""Semantic tool search endpoints for User domain."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db

from user.api.schemas import ToolSearchResponse, ToolSearchResult
from user.services.catalog_engine import (
    get_relevant_tools_semantic,
    get_user_connected_server_ids,
)

logger = logging.getLogger("user.tools")

router = APIRouter()


@router.get("/catalog/tools", response_model=ToolSearchResponse)
async def search_catalog_tools(
    q: str,
    top_k_servers: int = 5,
    top_k_tools: int = 8,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Two-stage semantic tool search: query -> top MCP servers -> top tools
    within them. Returns each tool's ``input_schema`` (parameters) so an LLM
    can be asked to fill them in — this endpoint does NOT call any tool.
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="q is required"
        )
    top_k_servers = min(max(top_k_servers, 1), 20)
    top_k_tools = min(max(top_k_tools, 1), 50)

    matches = await get_relevant_tools_semantic(
        db,
        user=user,
        query=q.strip(),
        top_k_servers=top_k_servers,
        top_k_tools=top_k_tools,
    )
    connected_ids = await get_user_connected_server_ids(
        db, server_ids=list({server.id for server, _tool, _score in matches}), user_id=user.id
    )
    # Only ever surface tools from servers the caller has connected their
    # own credential for — a matching tool on an unconnected server is
    # dropped from `results`, not shown, and its server id is reported
    # separately so the client can offer "Connect" instead.
    results = [
        ToolSearchResult(
            tool_id=tool.id,
            tool_name=tool.name,
            tool_description=tool.description,
            input_schema=tool.input_schema,
            server_id=server.id,
            server_name=server.name,
            score=score,
        )
        for server, tool, score in matches
        if server.id in connected_ids
    ]
    needs_connection_server_ids = sorted(
        {server.id for server, _tool, _score in matches if server.id not in connected_ids}
    )
    return ToolSearchResponse(
        results=results,
        count=len(results),
        needs_connection_server_ids=needs_connection_server_ids,
    )
