"""Type definitions, constants, and credential field maps for mcp_detect."""
from __future__ import annotations

_PROBE_TIMEOUT = 10.0

# A minimal but valid MCP initialize request, used to classify the endpoint.
_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "enterpriseai-probe", "version": "1.0.0"},
    },
}

# RFC 9728 protected-resource metadata location (relative to the resource).
_PROTECTED_RESOURCE_WELLKNOWN = "/.well-known/oauth-protected-resource"
# RFC 8414 / OIDC authorization-server metadata locations (relative to issuer).
_AUTH_SERVER_WELLKNOWN_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
)

# Mapping from legacy string confidence values to float scores.
_CONFIDENCE_FLOAT: dict[str, float] = {
    "command":    1.00,  # stdio — no network ambiguity
    "open":       0.99,  # 200 on POST → streamable_http (updated inline for SSE)
    "challenge":  0.80,  # 401/403 on POST → streamable_http, auth required
    "well-known": 0.70,  # OAuth metadata discovered without a live probe
    "hint":       0.50,  # heuristic / fallback
    "none":       0.10,  # unreachable
}


class McpDetectError(Exception):
    """Raised when detection cannot be performed at all (invalid input)."""


def _credential_fields(auth_type: str) -> list[dict]:
    """The credential form fields a UI should render for the given auth type."""
    if auth_type in ("bearer", "oauth2"):
        fields = [
            {
                "name": "access_token",
                "label": "Access token" if auth_type == "oauth2" else "Bearer token",
                "type": "password",
                "placeholder": "eyJhbGciOi…",
                "secret": True,
                "required": True,
            }
        ]
        if auth_type == "oauth2":
            fields += [
                {"name": "client_id", "label": "Client ID", "type": "text", "placeholder": "", "secret": False, "required": False},
                {"name": "client_secret", "label": "Client secret", "type": "password", "placeholder": "", "secret": True, "required": False},
            ]
        return fields
    if auth_type == "api_key":
        return [
            {"name": "api_key", "label": "API key", "type": "password", "placeholder": "sk-…", "secret": True, "required": True}
        ]
    if auth_type == "basic":
        return [
            {"name": "username", "label": "Username", "type": "text", "placeholder": "user@example.com", "secret": False, "required": True},
            {"name": "password", "label": "Password / API token", "type": "password", "placeholder": "", "secret": True, "required": True},
        ]
    return []
