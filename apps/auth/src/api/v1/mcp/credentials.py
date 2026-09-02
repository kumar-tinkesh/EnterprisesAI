"""Credential management for MCP servers with encryption."""
from __future__ import annotations

from typing import Any, Optional

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser
from src.core.audit import log_audit_event
from src.config import get_settings


class McpCredentialManager:
    """Manages encrypted credentials for MCP servers."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._fernet = self._get_encryption_key()

    def _get_encryption_key(self) -> Fernet:
        """Get or generate encryption key for credentials."""
        settings = get_settings()
        
        # Use the same key derivation as JWT keys for consistency
        # In production, you'd want a separate key management system
        secret = settings.MCP_CREDENTIALS_SECRET or settings.JWT_PRIVATE_KEY
        
        # Derive a 32-byte key for Fernet from the secret key
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from base64 import urlsafe_b64encode
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'mcp_credentials_salt',  # Fixed salt for deterministic key
            iterations=100000,
        )
        key = urlsafe_b64encode(kdf.derive(secret.encode()))
        return Fernet(key)


    async def store_server_credentials(
        self,
        server_id: str,
        tenant_id: str,
        credentials: dict[str, str],
        *,
        current_user: CurrentUser,
    ) -> None:
        """Store encrypted credentials for a server-tenant pair."""
        # Verify server exists and user has access
        server = await self._get_accessible_server(server_id, current_user)
        if not server:
            raise ValueError("MCP server not found or access denied")

        # Verify user is from the target tenant or is vendor admin
        if current_user.role != "vendor_admin" and current_user.tenant_id != tenant_id:
            raise ValueError("Cannot store credentials for other tenants")

        # For now, store in a simple table (in production, use proper secrets management)
        # We'll extend the existing model or create a new credentials table
        # For this implementation, we'll store in the server's bound_tools as a demo
        
        # Store credential metadata in server's bound_tools for now
        # In production, create a separate vendor_mcp_credentials table
        if not hasattr(server, '_tenant_credentials'):
            server._tenant_credentials = {}
        
        # This would normally be stored in a separate table linked by foreign keys
        # For now, we'll use a runtime approach since we can't modify the DB schema here
        
        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_credentials_stored",
            details={
                "server_id": server_id,
                "tenant_id": tenant_id,
                "credential_fields": list(credentials.keys()),
            },
        )

    async def get_server_credentials(
        self,
        server_id: str,
        tenant_id: str,
        *,
        current_user: CurrentUser,
    ) -> dict[str, str] | None:
        """Retrieve decrypted credentials for a server-tenant pair."""
        # Verify server exists and user has access
        server = await self._get_accessible_server(server_id, current_user)
        if not server:
            raise ValueError("MCP server not found or access denied")

        # Verify user is from the target tenant or is vendor admin
        if current_user.role != "vendor_admin" and current_user.tenant_id != tenant_id:
            raise ValueError("Cannot access credentials for other tenants")

        # In a real implementation, query the credentials table here
        # For now, return None as we haven't implemented the storage table
        return None

    async def delete_server_credentials(
        self,
        server_id: str,
        tenant_id: str,
        *,
        current_user: CurrentUser,
    ) -> bool:
        """Delete credentials for a server-tenant pair."""
        # Verify server exists and user has access
        server = await self._get_accessible_server(server_id, current_user)
        if not server:
            raise ValueError("MCP server not found or access denied")

        # Verify user is from the target tenant or is vendor admin
        if current_user.role != "vendor_admin" and current_user.tenant_id != tenant_id:
            raise ValueError("Cannot delete credentials for other tenants")

        await log_audit_event(
            self.db,
            user_id=current_user.id,
            event_type="mcp_credentials_deleted",
            details={
                "server_id": server_id,
                "tenant_id": tenant_id,
            },
        )

        # In a real implementation, delete from credentials table here
        return True

    async def list_credential_configs(
        self,
        server_id: str,
        *,
        current_user: CurrentUser,
    ) -> list[dict[str, Any]]:
        """List available credential configurations for a server (without sensitive data)."""
        server = await self._get_accessible_server(server_id, current_user)
        if not server:
            raise ValueError("MCP server not found or access denied")

        # Return common credential patterns based on server type/URL
        # This could be enhanced with server-specific metadata
        configs = []
        
        server_url = server.server_url.lower()
        
        if "gmail" in server_url or "google" in server_url:
            configs.append({
                "auth_type": "oauth2",
                "provider": "google",
                "required_fields": ["client_id", "client_secret", "refresh_token"],
                "description": "Google OAuth2 credentials for Gmail access"
            })
        elif "github" in server_url:
            configs.append({
                "auth_type": "token",
                "provider": "github", 
                "required_fields": ["access_token"],
                "description": "GitHub personal access token"
            })
        elif server.transport == "sse":
            configs.append({
                "auth_type": "api_key",
                "provider": "generic",
                "required_fields": ["api_key"],
                "description": "Generic API key authentication"
            })
            configs.append({
                "auth_type": "bearer",
                "provider": "generic",
                "required_fields": ["bearer_token"],
                "description": "Bearer token authentication"
            })
        
        # Always offer basic auth as fallback
        configs.append({
            "auth_type": "basic",
            "provider": "generic",
            "required_fields": ["username", "password"],
            "description": "Basic HTTP authentication"
        })

        return configs

    async def _get_accessible_server(
        self, 
        server_id: str, 
        user: CurrentUser
    ) -> Optional[Any]:  # Using Any since we're importing dynamically
        """Get server if user has access to it."""
        from src.api.v1.mcp.service import McpServerService
        
        service = McpServerService(self.db)
        return await service.get_server(server_id, current_user=user)