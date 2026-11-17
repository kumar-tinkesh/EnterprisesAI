"""Pydantic schemas for MCP server management."""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator


class McpServerBase(BaseModel):
    """Base MCP server fields."""
    name: str = Field(..., min_length=1, max_length=255, description="Server name")
    description: str = Field("", max_length=2000, description="Server description")
    transport: str = Field("sse", pattern="^(sse|stdio)$", description="Transport type (sse or stdio)")
    server_url: HttpUrl = Field(..., description="MCP server URL")
    is_global: bool = Field(False, description="Available to all tenants without explicit grants")


class McpServerCreate(McpServerBase):
    """Schema for creating a new MCP server."""
    bound_tools: list[dict[str, Any]] = Field(
        default_factory=list, 
        description="Auto-discovered tools from the server"
    )


class McpServerUpdate(BaseModel):
    """Schema for updating an MCP server."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    transport: Optional[str] = Field(None, pattern="^(sse|stdio)$")
    server_url: Optional[HttpUrl] = None
    bound_tools: Optional[list[dict[str, Any]]] = None
    is_global: Optional[bool] = None


class McpServerOut(McpServerBase):
    """Schema for MCP server output."""
    id: str
    bound_tools: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    
    # Include grant information for non-global servers
    tenant_grants: Optional[list["TenantResourceGrantOut"]] = Field(
        None, description="Tenant grants (only for vendor admins)"
    )

    model_config = {"from_attributes": True}



# Tenant Resource Grant schemas
class TenantResourceGrantBase(BaseModel):
    """Base tenant resource grant fields."""
    tenant_id: str
    resource_type: str = Field(..., pattern="^(mcp_server|datasource)$")
    resource_id: str


class TenantResourceGrantCreate(TenantResourceGrantBase):
    """Schema for creating a tenant resource grant."""
    pass


class TenantResourceGrantOut(TenantResourceGrantBase):
    """Schema for tenant resource grant output."""
    id: str
    created_at: datetime
    updated_at: datetime
    
    # Optional nested resource info
    mcp_server: Optional[McpServerOut] = None

    model_config = {"from_attributes": True}


# Credential management schemas
class McpServerCredentials(BaseModel):
    """Credentials for MCP server access."""
    credentials: dict[str, str] = Field(..., description="Credential key-value pairs")
    
    @field_validator('credentials')
    @classmethod
    def validate_credentials(cls, v: dict[str, str]) -> dict[str, str]:
        """Ensure credentials are strings."""
        if not isinstance(v, dict):
            raise ValueError("Credentials must be a dictionary")
        
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("All credential keys and values must be strings")
        
        return v


class McpServerWithAccess(McpServerOut):
    """MCP server with user access information."""
    has_access: bool = Field(..., description="Whether current user/tenant has access")
    access_via: str = Field(..., description="Access method: 'global', 'tenant_grant', or 'none'")


# List response schemas
class McpServerListResponse(BaseModel):
    """Response for listing MCP servers."""
    servers: list[McpServerWithAccess]
    total: int
    has_next: bool = False
    has_prev: bool = False


# Update forward references
McpServerOut.model_rebuild()
TenantResourceGrantOut.model_rebuild()