"""Native, standards-driven MCP credential resolution engine package.

Consolidates crypto, storage (DB & cache), header builders, OAuth2 flows,
and the main resolver engine into a modular package layout while preserving
100% backward compatibility for all imports and unit test monkeypatches.
"""
from __future__ import annotations

from vendor.services.mcp_auth.crypto import (
    McpAuthError,
    decrypt_credentials,
    encrypt_credentials,
)
from vendor.services.mcp_auth.storage import (
    _TOKEN_EXPIRY_MARGIN,
    _cache_get,
    _cache_key,
    _cache_put,
    _token_cache,
    clear_token_cache,
    delete_server_credentials,
    delete_user_credential,
    has_user_credential,
    load_server_credentials,
    store_server_credentials,
)
from vendor.services.mcp_auth.oauth import (
    _DEFAULT_TIMEOUT,
    _KNOWN_AUTH_HEADERS,
    _api_key_header,
    _basic_header,
    _bearer_header,
    _client_credentials_grant,
    _dynamically_register_client,
    _merge_scopes,
    _new_client,
    _raw_header_passthrough,
    _refresh_token_grant,
    _resolve_oauth2,
    _token_request,
    exchange_authorization_code,
)
from vendor.services.mcp_auth.resolver import resolve_auth

__all__ = [
    "McpAuthError",
    "encrypt_credentials",
    "decrypt_credentials",
    "store_server_credentials",
    "load_server_credentials",
    "has_user_credential",
    "delete_server_credentials",
    "delete_user_credential",
    "_TOKEN_EXPIRY_MARGIN",
    "_token_cache",
    "_cache_key",
    "_cache_get",
    "_cache_put",
    "clear_token_cache",
    "_DEFAULT_TIMEOUT",
    "_KNOWN_AUTH_HEADERS",
    "_basic_header",
    "_api_key_header",
    "_bearer_header",
    "_raw_header_passthrough",
    "_new_client",
    "_token_request",
    "_merge_scopes",
    "_client_credentials_grant",
    "_refresh_token_grant",
    "exchange_authorization_code",
    "_dynamically_register_client",
    "_resolve_oauth2",
    "resolve_auth",
]
