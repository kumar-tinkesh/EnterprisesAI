"""Native MCP server detection package."""
from __future__ import annotations

import httpx

from vendor.services.mcp_detect.detector import _result, detect_mcp_server
from vendor.services.mcp_detect.probes import (
    _authorization_server_metadata,
    _base_url,
    _candidate_urls,
    _classify_challenge,
    _discover_oauth_metadata,
    _fetch_json,
    _probe_endpoint,
    _resource_metadata_url,
)
from vendor.services.mcp_detect.types import (
    _AUTH_SERVER_WELLKNOWN_PATHS,
    _CONFIDENCE_FLOAT,
    _INITIALIZE_BODY,
    _PROBE_TIMEOUT,
    _PROTECTED_RESOURCE_WELLKNOWN,
    McpDetectError,
    _credential_fields,
)

__all__ = [
    "httpx",
    "McpDetectError",
    "detect_mcp_server",
    "_result",
    "_credential_fields",
    "_candidate_urls",
    "_classify_challenge",
    "_probe_endpoint",
    "_resource_metadata_url",
    "_fetch_json",
    "_authorization_server_metadata",
    "_discover_oauth_metadata",
    "_base_url",
    "_PROBE_TIMEOUT",
    "_INITIALIZE_BODY",
    "_PROTECTED_RESOURCE_WELLKNOWN",
    "_AUTH_SERVER_WELLKNOWN_PATHS",
    "_CONFIDENCE_FLOAT",
]
