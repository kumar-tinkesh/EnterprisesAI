"""Tool Call Planner endpoints for User domain."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db

from user.api.schemas import PlannedToolCall, ToolCallPlanResponse
from user.services.tool_call_planner import plan_tool_call

logger = logging.getLogger("user.planner")

router = APIRouter()


@router.get("/catalog/plan-tool-call", response_model=ToolCallPlanResponse)
async def plan_tool_call_endpoint(
    q: str,
    top_k_servers: int = 5,
    top_k_tools: int = 3,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Select ONE MCP tool for the query and fill its arguments via the chat
    LLM's native function-calling, using the same access-filtered semantic
    candidates as ``GET /catalog/tools``. Does NOT call the tool — the
    response is the proposed tool + filled arguments only.
    """
    if not q or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="q is required"
        )
    top_k_servers = min(max(top_k_servers, 1), 20)
    top_k_tools = min(max(top_k_tools, 1), 10)

    result = await plan_tool_call(
        db,
        user=user,
        query=q.strip(),
        top_k_servers=top_k_servers,
        top_k_tools=top_k_tools,
    )
    plan = (
        PlannedToolCall(
            tool_id=result.plan.tool_id,
            tool_name=result.plan.tool_name,
            server_id=result.plan.server_id,
            server_name=result.plan.server_name,
            arguments=result.plan.arguments,
            input_schema=result.plan.input_schema,
            model=result.plan.model,
        )
        if result.plan
        else None
    )
    return ToolCallPlanResponse(
        plan=plan,
        candidates_considered=result.candidates_considered,
        message=result.message,
        needs_connection_server_id=result.needs_connection_server_id,
    )
