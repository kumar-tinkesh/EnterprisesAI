"""Pre-connection analysis, URL probing, and repo detection endpoints (Admin)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import CurrentUser, require_roles
from src.core.roles import Roles

from vendor.api.v1.schemas import (
    AnalyzeRepoRequest,
    AnalyzeRepoResponse,
    McpDetectRequest,
    McpDetectResponse,
)
from vendor.services.mcp_detect import McpDetectError, detect_mcp_server
from vendor.services.repo_analyzer import analyze_repo

logger = logging.getLogger("vendor.detection")

router = APIRouter()
_admin = Depends(require_roles(Roles.VENDOR_ADMIN))


@router.post("/mcp/detect", response_model=McpDetectResponse)
async def detect_mcp_server_endpoint(
    payload: McpDetectRequest,
    _user: CurrentUser = _admin,
):
    """Natively probe any MCP URL/command and report which credential type it wants."""
    try:
        result = await detect_mcp_server(payload.server_url)
    except McpDetectError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result


@router.post(
    "/mcp/analyze-repo",
    response_model=AnalyzeRepoResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze_mcp_repo_endpoint(
    payload: AnalyzeRepoRequest,
    _user: CurrentUser = _admin,
):
    """Analyze a GitHub repository or direct endpoint for MCP characteristics."""
    try:
        result = await analyze_repo(payload.repo_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository analysis failed: {str(exc)}",
        ) from exc
    return result
