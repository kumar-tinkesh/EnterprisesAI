"""MCP server management API router."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user, get_db, require_roles
from src.api.v1.mcp.schemas import (
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpServerWithAccess,
    McpServerListResponse,
    TenantResourceGrantCreate,
    TenantResourceGrantOut,
    McpServerCredentials,
)
from src.api.v1.mcp.service import McpServerService
from src.api.v1.mcp.credentials import McpCredentialManager


router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("/servers", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    server_data: McpServerCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_roles(["vendor_admin"]))],
) -> McpServerOut:
    """Create a new MCP server (vendor admin only)."""
    service = McpServerService(db)
    
    try:
        server = await service.create_server(
            name=server_data.name,
            description=server_data.description,
            transport=server_data.transport,
            server_url=str(server_data.server_url),
            bound_tools=server_data.bound_tools,
            is_global=server_data.is_global,
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    return McpServerOut.model_validate(server)


@router.get("/servers", response_model=McpServerListResponse)
async def list_mcp_servers(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    include_inaccessible: bool = Query(False, description="Include servers user cannot access"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> McpServerListResponse:
    """List MCP servers based on user access."""
    service = McpServerService(db)
    
    servers = await service.list_servers(
        current_user=current_user,
        include_inaccessible=include_inaccessible,
        limit=limit,
        offset=offset,
    )
    
    # Add access information to each server
    servers_with_access = []
    for server in servers:
        has_access = await service._has_server_access(server, current_user)
        
        # Determine access method
        if current_user.role == "vendor_admin":
            access_via = "vendor_admin"
        elif server.is_global:
            access_via = "global"
        elif has_access:
            access_via = "tenant_grant"
        else:
            access_via = "none"
        
        server_dict = McpServerOut.model_validate(server).model_dump()
        server_with_access = McpServerWithAccess(
            **server_dict,
            has_access=has_access,
            access_via=access_via,
        )
        servers_with_access.append(server_with_access)
    
    return McpServerListResponse(
        servers=servers_with_access,
        total=len(servers_with_access),
        has_next=len(servers) == limit,  # Simple approximation
        has_prev=offset > 0,
    )


@router.get("/servers/{server_id}", response_model=McpServerOut)
async def get_mcp_server(
    server_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> McpServerOut:
    """Get a specific MCP server."""
    service = McpServerService(db)
    
    server = await service.get_server(server_id, current_user=current_user)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found or access denied"
        )
    
    return McpServerOut.model_validate(server)


@router.put("/servers/{server_id}", response_model=McpServerOut)
async def update_mcp_server(
    server_id: str,
    server_data: McpServerUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_roles(["vendor_admin"]))],
) -> McpServerOut:
    """Update MCP server (vendor admin only)."""
    service = McpServerService(db)
    
    try:
        server = await service.update_server(
            server_id,
            name=server_data.name,
            description=server_data.description,
            transport=server_data.transport,
            server_url=str(server_data.server_url) if server_data.server_url else None,
            bound_tools=server_data.bound_tools,
            is_global=server_data.is_global,
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found"
        )
    
    return McpServerOut.model_validate(server)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_roles(["vendor_admin"]))],
):
    """Delete MCP server (vendor admin only)."""
    service = McpServerService(db)
    
    try:
        deleted = await service.delete_server(server_id, current_user=current_user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found"
        )


@router.post("/servers/{server_id}/grants", response_model=TenantResourceGrantOut, status_code=status.HTTP_201_CREATED)
async def grant_server_access(
    server_id: str,
    grant_data: TenantResourceGrantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_roles(["vendor_admin"]))],
) -> TenantResourceGrantOut:
    """Grant tenant access to MCP server (vendor admin only)."""
    if grant_data.resource_type != "mcp_server":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resource type must be 'mcp_server'"
        )
    
    if grant_data.resource_id != server_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resource ID must match server ID"
        )
    
    service = McpServerService(db)
    
    try:
        grant = await service.grant_server_access(
            server_id,
            grant_data.tenant_id,
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    return TenantResourceGrantOut.model_validate(grant)


@router.delete("/servers/{server_id}/grants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_server_access(
    server_id: str,
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_roles(["vendor_admin"]))],
):
    """Revoke tenant access to MCP server (vendor admin only)."""
    service = McpServerService(db)
    
    try:
        revoked = await service.revoke_server_access(
            server_id,
            tenant_id,
            current_user=current_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grant not found"
        )


# Health check endpoint for MCP server connectivity
@router.post("/servers/{server_id}/test", status_code=status.HTTP_200_OK)
async def test_mcp_server_connection(
    server_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, str]:
    """Test connectivity to MCP server."""
    service = McpServerService(db)
    
    server = await service.get_server(server_id, current_user=current_user)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found or access denied"
        )
    
    # Basic connectivity test
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(server.server_url, timeout=5.0)
            if response.status_code < 500:
                return {"status": "success", "message": "Server is reachable"}
            else:
                return {"status": "error", "message": f"Server returned {response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


# Credential management endpoints
@router.get("/servers/{server_id}/credentials/configs")
async def get_credential_configs(
    server_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, list[dict]]:
    """Get available credential configuration options for a server."""
    credential_manager = McpCredentialManager(db)
    
    try:
        configs = await credential_manager.list_credential_configs(
            server_id, current_user=current_user
        )
        return {"credential_configs": configs}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/servers/{server_id}/credentials/{tenant_id}", status_code=status.HTTP_201_CREATED)
async def store_server_credentials(
    server_id: str,
    tenant_id: str,
    credentials: McpServerCredentials,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, str]:
    """Store encrypted credentials for MCP server access."""
    credential_manager = McpCredentialManager(db)
    
    try:
        await credential_manager.store_server_credentials(
            server_id,
            tenant_id,
            credentials.credentials,
            current_user=current_user,
        )
        return {"status": "success", "message": "Credentials stored successfully"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/servers/{server_id}/credentials/{tenant_id}")
async def get_server_credentials(
    server_id: str,
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, dict]:
    """Retrieve decrypted credentials (admin only - for testing/debugging)."""
    # Only allow vendor admins to retrieve raw credentials
    if current_user.role != "vendor_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only vendor admins can retrieve raw credentials"
        )
    
    credential_manager = McpCredentialManager(db)
    
    try:
        credentials = await credential_manager.get_server_credentials(
            server_id,
            tenant_id,
            current_user=current_user,
        )
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No credentials found for this server-tenant pair"
            )
        
        return {"credentials": credentials}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/servers/{server_id}/credentials/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server_credentials(
    server_id: str,
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """Delete stored credentials for MCP server access."""
    credential_manager = McpCredentialManager(db)
    
    try:
        deleted = await credential_manager.delete_server_credentials(
            server_id,
            tenant_id,
            current_user=current_user,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No credentials found for this server-tenant pair"
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))