"""Builder REST endpoints (mounted at ``/api/v1/builder``).

Routes (agents and workflows: see ``agents.py`` / ``workflows.py``):
    GET  /servers/{server_id}/tools   a server's tools with their risk level, and
                                      whether the caller has connected it
    POST /tools/invoke                run one tool as the caller

For end users only (tenant admins/users and solo users): a vendor admin
tests servers through the vendor connect flow instead. Every invocation is
audit-logged (tool, risk, outcome — never the arguments, which can hold
personal data or secrets).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.audit import log_audit_event
from src.db.session import get_db

from vendor.models import MCPTool
from vendor.services import mcp_auth
from vendor.services.mcp_service.crud import get_mcp_server, is_server_visible_to_user

from builder.api.v1 import agents, assist, runs, workflows
from builder.api.v1.deps import get_end_user
from builder.api.v1.schemas import (
    RuntimeToolOut,
    ServerToolsResponse,
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolRiskOut,
)
from builder.services.tool_runtime import (
    ConfirmationRequired,
    InvalidArguments,
    NotConnected,
    ToolRisk,
    ToolRuntimeError,
    ToolTimeout,
    ToolUnavailable,
    classify_tool,
    invoke_tool,
)

router = APIRouter()
router.include_router(agents.router, prefix="/agents")
router.include_router(workflows.router, prefix="/workflows")
router.include_router(runs.router)
router.include_router(assist.router)


def _risk_out(risk: ToolRisk) -> ToolRiskOut:
    return ToolRiskOut(risk=risk.risk, reason=risk.reason, needs_confirmation=risk.needs_confirmation)


def _error_response(exc: ToolRuntimeError) -> JSONResponse:
    body: dict = {"detail": exc.message, "error": type(exc).__name__}
    if isinstance(exc, NotConnected):
        body["server_id"] = exc.server_id
    if isinstance(exc, InvalidArguments):
        body["errors"] = exc.errors
    if isinstance(exc, ConfirmationRequired):
        body["risk"] = exc.risk
    if isinstance(exc, ToolUnavailable):
        body["may_have_run"] = exc.may_have_run
    return JSONResponse(status_code=exc.status_code, content=body)


@router.get("/servers/{server_id}/tools", response_model=ServerToolsResponse)
async def list_server_tools(
    server_id: str,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    server = await get_mcp_server(db, server_id)
    if server is None or not await is_server_visible_to_user(db, user=user, server=server):
        raise HTTPException(status_code=404, detail="MCP server not found.")
    tools = (
        await db.execute(select(MCPTool).where(MCPTool.mcp_server_id == server.id).order_by(MCPTool.name))
    ).scalars().all()
    return ServerToolsResponse(
        server_id=server.id,
        server_name=server.name,
        connected=await mcp_auth.has_user_credential(db, server_id=server.id, user_id=user.id),
        tools=[
            RuntimeToolOut(
                name=t.name,
                description=t.description or "",
                input_schema=t.input_schema,
                risk=_risk_out(classify_tool(t.name, t.annotations)),
            )
            for t in tools
        ],
    )


@router.post("/tools/invoke", response_model=ToolInvokeResponse)
async def invoke_tool_endpoint(
    payload: ToolInvokeRequest,
    user: CurrentUser = Depends(get_end_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await invoke_tool(
            db,
            user=user,
            server_id=payload.server_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            confirm=payload.confirm,
            timeout=payload.timeout_seconds,
        )
    except ToolRuntimeError as exc:
        # Calls refused before anything ran (not found, not connected, bad
        # arguments, unconfirmed) aren't audited; failures while running are.
        if isinstance(exc, (ToolUnavailable, ToolTimeout)):
            await _audit(db, user, payload, outcome=type(exc).__name__)
        return _error_response(exc)

    await _audit(
        db,
        user,
        payload,
        outcome="tool_error" if result.output.is_error else "ok",
        risk=result.risk.risk,
        duration_ms=result.duration_ms,
    )
    out = result.output
    return ToolInvokeResponse(
        server_id=result.server_id,
        server_name=result.server_name,
        tool_name=result.tool_name,
        risk=_risk_out(result.risk),
        is_error=out.is_error,
        text=out.text,
        structured=out.structured,
        content=out.content,
        truncated=out.truncated,
        duration_ms=result.duration_ms,
        attempts=result.attempts,
    )


async def _audit(
    db: AsyncSession,
    user: CurrentUser,
    payload: ToolInvokeRequest,
    *,
    outcome: str,
    risk: str | None = None,
    duration_ms: int | None = None,
) -> None:
    detail = f"tool={payload.tool_name} outcome={outcome}"
    if risk:
        detail += f" risk={risk}"
    if duration_ms is not None:
        detail += f" duration_ms={duration_ms}"
    await log_audit_event(
        db,
        action="builder.tool_invoke",
        user_id=user.id,
        tenant_id=user.tenant_id,
        resource=f"mcp_server:{payload.server_id}",
        detail=detail,
    )
    await db.commit()
