"""MCP client helper — auto-detects transport and discovers tools.

Connects to an MCP server over the official ``mcp`` SDK, performing the MCP
handshake (``initialize``) and ``tools/list`` discovery. Supported transports:

- ``streamable_http`` — POST-based streamable HTTP (modern MCP servers)
- ``sse``             — GET-based Server-Sent Events (legacy MCP servers)
- ``stdio``           — a local command string (``npx -y some-mcp-server …``)

Credentials are injected per transport, mirroring the MRKTPLCE ``mcp_runtime``
design: auth *headers* for network transports, environment variables for
spawned stdio processes.
"""
from __future__ import annotations

import base64
import logging
import os
import shlex
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger("vendor_resources.mcp_client")

_DEFAULT_TIMEOUT = 30.0

# Package runners resolve their own dependencies/entry points from a registry —
# they never need a local source checkout, so ``source_repo_url`` must NOT
# trigger a repo clone when the command uses one of these.
_PACKAGE_RUNNER_COMMANDS = {
    "npx", "npm", "pnpm", "pnpx", "pip", "pipx", "uv", "uvx",
    "docker", "deno", "bun", "bunx",
}

_REPO_CLONE_TIMEOUT = 120  # seconds (was 30 — too tight for constrained networks)
_REPO_BUILD_TIMEOUT = 120

# Header names a caller may pass in ``credentials`` verbatim (backward-compat:
# older clients sent a raw header map). Anything else is mapped via auth_type.
_KNOWN_AUTH_HEADERS = {"authorization", "x-api-key", "api-key", "x-auth-token"}


def _detect_transport(server_url: str) -> str:
    """Auto-detect transport from the server URL/command string."""
    if server_url.startswith("http://") or server_url.startswith("https://"):
        return "streamable_http"
    return "stdio"


def _build_auth_headers(
    credentials: dict[str, str] | None,
    auth_type: str | None = None,
) -> dict[str, str]:
    """Map a credentials dict + detected auth type into HTTP auth headers.

    Mapping rules (``auth_type`` comes from ``services.mcp_detect``):
      - ``bearer``/``oauth2`` → ``Authorization: Bearer <token>``
      - ``api_key``           → ``X-API-Key: <key>`` (or ``Authorization`` if
        the caller supplied a header-named key directly)
      - ``basic``             → ``Authorization: Basic base64(user:pass)``
      - ``none``/unknown      → raw header passthrough (legacy behaviour)
    """
    if not credentials:
        return {}

    # Raw header passthrough takes precedence for backward compatibility:
    # previously the whole credentials dict was used as headers.
    direct = {
        k: v
        for k, v in credentials.items()
        if k.lower() in _KNOWN_AUTH_HEADERS or ":" in k
    }
    if direct and auth_type in (None, "", "none", "unknown"):
        return direct

    auth_type = (auth_type or "").lower()
    headers: dict[str, str] = {}

    if auth_type == "basic":
        username = credentials.get("username", "")
        password = credentials.get("password", "")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    elif auth_type in ("bearer", "oauth2"):
        token = (
            credentials.get("access_token")
            or credentials.get("token")
            or credentials.get("bearer_token")
            or credentials.get("api_key")
            or ""
        )
        if token:
            if token.startswith("Bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        api_key = (
            credentials.get("api_key")
            or credentials.get("api-key")
            or credentials.get("x-api-key")
            or ""
        )
        if api_key:
            header_name = credentials.get("header_name") or "X-API-Key"
            if header_name.lower() == "authorization":
                prefix = credentials.get("header_prefix", "Bearer ")
                headers["Authorization"] = f"{prefix}{api_key}"
            else:
                headers[header_name] = api_key
    elif direct:
        return direct

    # Merge any explicit raw headers on top.
    headers.update(direct)
    return headers


def _normalize_tool(tool: Any) -> dict[str, Any]:
    """Normalize an MCP tool model into a plain dict with full metadata."""
    return {
        "name": tool.name,
        "description": getattr(tool, "description", "") or "",
        "input_schema": getattr(tool, "input_schema", None)
        or {"type": "object", "properties": {}},
    }


async def _session_details(read_stream, write_stream) -> dict:
    """Run initialize + tools/list on an established transport pair."""
    async with ClientSession(read_stream=read_stream, write_stream=write_stream) as session:
        init = await session.initialize()
        result = await session.list_tools()
        tools = [_normalize_tool(t) for t in (result.tools or [])]
        server_info = getattr(init, "server_info", None)
        return {
            "server_info": {
                "name": getattr(server_info, "name", None),
                "version": getattr(server_info, "version", None),
            }
            if server_info
            else None,
            "protocol_version": getattr(init, "protocol_version", None),
            "tools": tools,
        }


async def _handshake(
    transport: str,
    server_url: str,
    headers: dict[str, str] | None,
    timeout: float,
) -> dict:
    """Perform the MCP handshake over an http(s) transport."""
    if transport == "streamable_http":
        async with httpx.AsyncClient(timeout=timeout, headers=headers or None) as http:
            async with streamable_http_client(server_url, http_client=http) as (
                read_stream,
                write_stream,
            ):
                return await _session_details(read_stream, write_stream)
    if transport == "sse":
        async with sse_client(server_url, headers=headers or None, timeout=timeout) as (
            read_stream,
            write_stream,
        ):
            return await _session_details(read_stream, write_stream)
    raise ValueError(f"Unsupported transport: {transport}")


async def connect_mcp_server(
    server_url: str,
    credentials: dict[str, str] | None = None,
    transport: str | None = None,
    auth_type: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    auth_headers: dict[str, str] | None = None,
    source_repo_url: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> dict:
    """Connect to an MCP server and return {transport, bound_tools, tools, ...}."""
    target = server_url.strip()
    transport = transport or _detect_transport(target)

    if transport == "stdio":
        return await _connect_stdio(
            target, credentials, source_repo_url=source_repo_url, env_vars=env_vars
        )

    headers = (
        auth_headers
        if auth_headers is not None
        else _build_auth_headers(credentials, auth_type)
    )
    attempts: list[str] = ["sse"] if transport == "sse" else ["streamable_http", "sse"]
    last_error: Exception | None = None
    for candidate in attempts:
        try:
            details = await _handshake(candidate, target, headers, timeout)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.debug("MCP handshake via %s failed for %s: %s", candidate, target, exc)
            continue
        logger.info(
            "%s connected to %s — discovered %d tool(s)",
            candidate,
            target,
            len(details["tools"]),
        )
        return {
            "transport": candidate,
            "bound_tools": [t["name"] for t in details["tools"]],
            "tools": details["tools"],
            "server_info": details["server_info"],
            "protocol_version": details["protocol_version"],
            "auth_type": auth_type or ("none" if not headers else "unknown"),
        }
    raise ConnectionError(f"Failed to connect via {attempts}: {last_error}")


async def _prepare_local_repo_stdio(
    command: str, source_repo_url: str | None
) -> tuple[str, list[str], str | None]:
    """Resolves stdio command parameters.

    Only fetches a GitHub repository when the *command itself* points at one
    (a GitHub URL, a ``git+`` specifier, or a bare relative entry point that
    cannot be resolved without the source tree). ``source_repo_url`` alone is
    treated as registration metadata: a self-resolving package runner such as
    ``npx -y @org/pkg`` never triggers a clone/download.
    """
    parts = shlex.split(command)
    cwd = None

    git_url: str | None = None
    if "github.com" in command or command.startswith("git+"):
        git_url = command
    elif source_repo_url and parts and parts[0] not in _PACKAGE_RUNNER_COMMANDS:
        # Bare entry point (e.g. "node dist/index.js") — needs the repo
        # checked out locally to be executable.
        git_url = source_repo_url

    if git_url and ("github.com" in git_url or git_url.startswith("http")):
        try:
            import re
            import subprocess
            from pathlib import Path

            match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", git_url)
            if match:
                owner, repo = match.groups()
                tmp_dir = Path("/tmp/mcp_repos") / f"{owner}_{repo}"
                tmp_dir.mkdir(parents=True, exist_ok=True)

                # Fetch the repo if not already cached locally.
                if not (tmp_dir / "package.json").exists() and not (tmp_dir / "pyproject.toml").exists():
                    try:
                        subprocess.run(
                            ["git", "clone", "--depth", "1", git_url, str(tmp_dir)],
                            check=True,
                            capture_output=True,
                            timeout=_REPO_CLONE_TIMEOUT,
                        )
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as clone_exc:
                        logger.warning(
                            "git clone failed for %s (%s); falling back to tarball download",
                            git_url,
                            clone_exc,
                        )
                        await _fetch_repo_tarball(owner, repo, tmp_dir)

                # Install dependencies & build if Node.js project
                if (tmp_dir / "package.json").exists():
                    subprocess.run(
                        ["npm", "install", "--no-audit", "--no-fund"],
                        cwd=tmp_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )
                    subprocess.run(
                        ["npm", "run", "build"],
                        cwd=tmp_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )

                cwd = str(tmp_dir)

                # Determine entry executable
                if (tmp_dir / "dist" / "index.js").exists():
                    parts = ["node", "dist/index.js"]
                elif (tmp_dir / "build" / "index.js").exists():
                    parts = ["node", "build/index.js"]
                elif (tmp_dir / "index.js").exists():
                    parts = ["node", "index.js"]
                elif (tmp_dir / "server.py").exists():
                    parts = ["python", "server.py"]
                elif (tmp_dir / "main.py").exists():
                    parts = ["python", "main.py"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed_to_prepare_local_repo %s: %s", git_url, exc)

    return parts[0], parts[1:], cwd


async def _fetch_repo_tarball(owner: str, repo: str, dest_dir) -> None:
    """Download and extract a GitHub repo tarball (fallback when ``git clone``
    is unavailable, blocked, or too slow). Tries ``main`` then ``master``."""
    import io
    import shutil
    import tarfile
    import tempfile
    from pathlib import Path

    last_status = 0
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        for branch in ("main", "master"):
            url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.tar.gz"
            resp = await client.get(url)
            if resp.status_code == 200:
                break
            last_status = resp.status_code
        else:
            raise ConnectionError(
                f"tarball download failed for {owner}/{repo} (HTTP {last_status})"
            )

    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
            tf.extractall(td, filter="data")  # noqa: S202 - extracts to sandboxed temp dir
        extracted = next(Path(td).iterdir())
        shutil.copytree(extracted, dest_dir, dirs_exist_ok=True)


async def _connect_stdio(
    command: str,
    credentials: dict[str, str] | None,
    source_repo_url: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> dict:
    """Spawn a stdio MCP server process, inject credentials and detected
    ``env_vars`` as environment variables and substitute ``{field}``
    placeholders in the command with credential values
    (e.g. ``npx -y x/y-mcp --token {api_key}``)."""
    env = {**os.environ}
    if isinstance(env_vars, dict):
        # Skip empty values and JSON "null" strings persisted by the UI.
        env.update(
            {
                str(k).upper(): str(v)
                for k, v in env_vars.items()
                if isinstance(v, str) and v.strip() and v.strip().lower() != "null"
            }
        )
    if credentials:
        env.update({k.upper(): v for k, v in credentials.items()})

    cmd_binary, cmd_args, cwd = await _prepare_local_repo_stdio(command, source_repo_url)

    params = StdioServerParameters(command=cmd_binary, args=cmd_args, env=env, cwd=cwd)
    async with stdio_client(params) as (read_stream, write_stream):
        details = await _session_details(read_stream, write_stream)
    logger.info("stdio connected to %s — discovered %d tool(s)", command, len(details["tools"]))
    return {
        "transport": "stdio",
        "bound_tools": [t["name"] for t in details["tools"]],
        "tools": details["tools"],
        "server_info": details["server_info"],
        "protocol_version": details["protocol_version"],
        "auth_type": "env" if credentials else "none",
    }

