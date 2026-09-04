"""MCP client helper — auto-detects transport and discovers tools.

Connects to an MCP server over the official ``mcp`` SDK, performing the MCP
handshake (``initialize``) and ``tools/list`` discovery. Supported transports:

- ``streamable_http`` — POST-based streamable HTTP (modern MCP servers)
- ``sse``             — GET-based Server-Sent Events (legacy MCP servers)
- ``stdio``           — a local command string (``npx -y some-mcp-server …``)

Credentials are injected per transport, mirroring the MRKTPLCE ``mcp_runtime``
design: auth *headers* for network transports, environment variables for
spawned stdio processes.

Public API
----------
``MCPClient``
    Object-oriented client with three adapter methods and a ``connect()``
    dispatcher. Accepts a normalized ``config`` dict (matching the new
    ``VendorMCPServer`` column layout) rather than the legacy flat parameters.

``connect_mcp_server()``
    Legacy free-function — kept for full backward compatibility with all
    existing callers throughout the codebase.
"""
from __future__ import annotations

import base64
import logging
import os
import shlex
import shutil
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


# ─────────────────────────────────────────────────────────────────────────────
# MCPClient — generic object-oriented client
# ─────────────────────────────────────────────────────────────────────────────


class MCPClient:
    """Generic MCP client — dispatches to the correct adapter based on transport.

    Usage::

        client = MCPClient()
        result = await client.connect(config)

    ``config`` is a normalized dict that mirrors the new ``VendorMCPServer``
    column layout.  The following keys are consumed:

    Common
    ~~~~~~
    - ``transport_type`` or ``transport``  — "stdio" | "streamable_http" | "sse"
    - ``auth_type``                        — from mcp_detect
    - ``credentials``                      — plain dict of credential values
    - ``timeout``                          — float seconds (default 30)

    stdio
    ~~~~~
    - ``command``           — binary/script to run (e.g. "npx -y @org/mcp")
    - ``args``              — list of extra arguments (appended after command)
    - ``working_directory`` — process CWD override
    - ``env_vars``          — extra environment variables dict
    - ``source_repo_url``   — GitHub repo URL for bare entry-point commands

    streamable_http / sse
    ~~~~~~~~~~~~~~~~~~~~~
    - ``endpoint``          — full URL including path (e.g. https://host/mcp)
    - ``auth_headers``      — pre-built header dict (takes precedence over
                              building from credentials + auth_type)
    """

    async def connect(self, config: dict) -> dict:
        """Connect using a normalized config dict.

        Dispatches to the appropriate adapter based on ``transport_type`` (or
        the legacy ``transport`` key). Returns the standard tools-discovery
        result dict.

        Raises ``ValueError`` for unsupported or missing transport types.
        """
        transport = config.get("transport_type") or config.get("transport")
        if transport == "stdio":
            return await self._stdio_adapter(config)
        elif transport == "streamable_http":
            return await self._streamable_http_adapter(config)
        elif transport == "sse":
            return await self._sse_adapter(config)
        else:
            raise ValueError(
                f"Unsupported transport: {transport!r}. "
                "Expected 'stdio', 'streamable_http', or 'sse'."
            )

    # ── Adapters ──────────────────────────────────────────────────────────

    async def _stdio_adapter(self, config: dict) -> dict:
        """STDIO adapter — spawns a local process and runs the MCP handshake.

        Config keys used:
          ``command``           — executable + args as a single string, or just
                                  the binary name (args are appended below).
          ``args``              — optional list of additional arguments appended
                                  to the command string.
          ``working_directory`` — process CWD (``cwd``); overrides any cwd
                                  derived from a repo clone.
          ``env_vars``          — extra environment variables to inject.
          ``credentials``       — injected as uppercased env vars (e.g.
                                  ``API_KEY=…``).
          ``source_repo_url``   — GitHub URL for bare entry points that need
                                  a local source tree.
        """
        command: str = config.get("command") or ""
        extra_args: list[str] = list(config.get("args") or [])
        if extra_args:
            # Append list args to the command string so _prepare_local_repo_stdio
            # can parse the whole thing with shlex.
            command = command.rstrip() + " " + " ".join(shlex.quote(a) for a in extra_args)

        credentials: dict[str, str] | None = config.get("credentials")
        source_repo_url: str | None = config.get("source_repo_url")
        env_vars: dict[str, str] | None = config.get("env_vars")
        working_directory: str | None = config.get("working_directory")
        timeout: float = float(config.get("timeout") or _DEFAULT_TIMEOUT)  # noqa: F841

        result = await _connect_stdio(
            command,
            credentials,
            source_repo_url=source_repo_url,
            env_vars=env_vars,
        )

        # Allow an explicit working_directory override in the config to
        # win over whatever _prepare_local_repo_stdio resolved from the repo.
        if working_directory:
            # The cwd is baked into the StdioServerParameters inside
            # _connect_stdio; we can only surface it in the result here for
            # informational purposes — the actual CWD was already set.
            result.setdefault("working_directory", working_directory)

        return result

    async def _streamable_http_adapter(self, config: dict) -> dict:
        """Streamable HTTP adapter — POST-based MCP over HTTP(S).

        Config keys used:
          ``endpoint``     — full URL (e.g. ``https://api.example.com/mcp``).
          ``auth_headers`` — pre-built header dict; takes precedence.
          ``credentials``  — fallback; converted to headers via ``auth_type``.
          ``auth_type``    — from mcp_detect (bearer/api_key/basic/oauth2/…).
          ``timeout``      — float seconds.
        """
        endpoint: str = config.get("endpoint") or config.get("server_url") or ""
        if not endpoint:
            raise ValueError("MCPClient._streamable_http_adapter: 'endpoint' is required")

        auth_type: str | None = config.get("auth_type")
        credentials: dict[str, str] | None = config.get("credentials")
        auth_headers: dict[str, str] | None = config.get("auth_headers")
        timeout: float = float(config.get("timeout") or _DEFAULT_TIMEOUT)

        headers = (
            auth_headers
            if auth_headers is not None
            else _build_auth_headers(credentials, auth_type)
        )

        details = await _handshake("streamable_http", endpoint, headers, timeout)
        logger.info(
            "streamable_http connected to %s — discovered %d tool(s)",
            endpoint,
            len(details["tools"]),
        )
        return {
            "transport": "streamable_http",
            "bound_tools": [t["name"] for t in details["tools"]],
            "tools": details["tools"],
            "server_info": details["server_info"],
            "protocol_version": details["protocol_version"],
            "auth_type": auth_type or ("none" if not headers else "unknown"),
        }

    async def _sse_adapter(self, config: dict) -> dict:
        """SSE adapter — GET-based Server-Sent Events transport.

        Config keys used:
          ``endpoint``     — full SSE URL (e.g. ``https://api.example.com/sse``).
          ``auth_headers`` — pre-built header dict; takes precedence.
          ``credentials``  — fallback; converted to headers via ``auth_type``.
          ``auth_type``    — from mcp_detect.
          ``timeout``      — float seconds.
        """
        endpoint: str = config.get("endpoint") or config.get("server_url") or ""
        if not endpoint:
            raise ValueError("MCPClient._sse_adapter: 'endpoint' is required")

        auth_type: str | None = config.get("auth_type")
        credentials: dict[str, str] | None = config.get("credentials")
        auth_headers: dict[str, str] | None = config.get("auth_headers")
        timeout: float = float(config.get("timeout") or _DEFAULT_TIMEOUT)

        headers = (
            auth_headers
            if auth_headers is not None
            else _build_auth_headers(credentials, auth_type)
        )

        details = await _handshake("sse", endpoint, headers, timeout)
        logger.info(
            "sse connected to %s — discovered %d tool(s)",
            endpoint,
            len(details["tools"]),
        )
        return {
            "transport": "sse",
            "bound_tools": [t["name"] for t in details["tools"]],
            "tools": details["tools"],
            "server_info": details["server_info"],
            "protocol_version": details["protocol_version"],
            "auth_type": auth_type or ("none" if not headers else "unknown"),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers (used by both MCPClient and the legacy connect_mcp_server)
# ─────────────────────────────────────────────────────────────────────────────


def _detect_transport(server_url: str) -> str:
    """Auto-detect transport from the server URL/command string."""
    if not server_url:
        return "stdio"
    url_lower = server_url.lower().strip()
    if "github.com" in url_lower:
        return "stdio"
    if url_lower.startswith("http://") or url_lower.startswith("https://"):
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


# ─────────────────────────────────────────────────────────────────────────────
# Legacy free-function — kept for full backward compatibility
# ─────────────────────────────────────────────────────────────────────────────


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
    """Connect to an MCP server and return {transport, bound_tools, tools, ...}.

    This is the legacy entry point used throughout the codebase.  It is kept
    unchanged for full backward compatibility — new code should prefer
    ``MCPClient().connect(config)`` instead.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# stdio helpers
# ─────────────────────────────────────────────────────────────────────────────


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
    elif source_repo_url and (not parts or parts[0] not in _PACKAGE_RUNNER_COMMANDS):
        # Bare entry point or empty command — needs the repo checked out locally to resolve executable/entry point.
        git_url = source_repo_url

    if git_url and ("github.com" in git_url or git_url.startswith("http")):
        try:
            import re
            import subprocess
            from pathlib import Path

            subpath = None
            subpath_match = re.search(r"/tree/[^/]+/(.+)$", git_url)
            if subpath_match:
                subpath = subpath_match.group(1).strip("/")

            match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", git_url)
            if match:
                owner, repo = match.groups()
                tmp_dir = Path("/tmp/mcp_repos") / f"{owner}_{repo}"
                canonical_git_url = f"https://github.com/{owner}/{repo}"

                def _has_manifest() -> bool:
                    if not tmp_dir.is_dir():
                        return False
                    check_dir = (tmp_dir / subpath) if (subpath and (tmp_dir / subpath).is_dir()) else tmp_dir
                    if (check_dir / "package.json").exists() or (check_dir / "pyproject.toml").exists() or (check_dir / "go.mod").exists():
                        return True
                    try:
                        return any(
                            (child / "package.json").exists()
                            or (child / "pyproject.toml").exists()
                            or (child / "go.mod").exists()
                            for child in check_dir.iterdir()
                            if child.is_dir() and not child.name.startswith(".")
                        )
                    except OSError:
                        return False

                if tmp_dir.exists() and not _has_manifest():
                    logger.info("removing stale repo cache %s", tmp_dir)
                    shutil.rmtree(tmp_dir, ignore_errors=True)

                if not _has_manifest():
                    try:
                        subprocess.run(
                            ["git", "clone", "--depth", "1", canonical_git_url, str(tmp_dir)],
                            check=True,
                            capture_output=True,
                            timeout=_REPO_CLONE_TIMEOUT,
                        )
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as clone_exc:
                        logger.warning(
                            "git clone failed for %s (%s); falling back to tarball download",
                            canonical_git_url,
                            clone_exc,
                        )
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        await _fetch_repo_tarball(owner, repo, tmp_dir)

                target_dir = (tmp_dir / subpath) if (subpath and (tmp_dir / subpath).is_dir()) else tmp_dir

                # Install dependencies & build if Node.js project
                if (target_dir / "package.json").exists():
                    subprocess.run(
                        ["npm", "install", "--no-audit", "--no-fund"],
                        cwd=target_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )
                    subprocess.run(
                        ["npm", "run", "build"],
                        cwd=target_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )

                # Download Go dependencies if this is a Go project
                if (target_dir / "go.mod").exists():
                    subprocess.run(
                        ["go", "mod", "download"],
                        cwd=target_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )

                cwd = str(target_dir)

                found = _pick_local_entry(target_dir)
                if found:
                    orig_extra = [
                        p for p in parts
                        if p not in ("go", "run", "node", "python", "uv", "npm", "npx", ".")
                        and not p.startswith("./")
                        and not any(p.endswith(ext) for ext in (".js", ".py", ".ts", ".go", ".mjs"))
                    ]
                    for extra in orig_extra:
                        if extra not in found:
                            found.append(extra)
                    parts = found
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed_to_prepare_local_repo %s: %s", git_url, exc)

    if not parts:
        raise ValueError(
            f"Invalid stdio command for {command!r}: unable to determine executable command or entry point."
        )

    return parts[0], parts[1:], cwd


def _python_module_base(root, mod: str):
    """Return the base dir (repo root or ``src/``) containing ``mod``."""
    rel = mod.replace(".", "/")
    for base in (root, root / "src"):
        if (base / f"{rel}.py").exists() or (base / rel / "__init__.py").exists():
            return base
    return None


def _python_console_entry_code(root, entry: str) -> str | None:
    """Build a ``python -c`` snippet that runs a console-script entry.

    ``entry`` is the ``[project.scripts]`` value — ``mod:obj`` or
    ``mod:obj.attr`` (e.g. ``mcp_weather.weather:mcp.run``). Not a
    ``python -m`` target: the object is imported and then called, mirroring
    the generated console-script wrapper. ``None`` when the module cannot be
    located in the repo (root or ``src/`` layout).
    """
    mod, _, obj_path = entry.partition(":")
    obj_path = obj_path.strip().strip("()")
    mod = mod.strip()
    if not mod or not obj_path:
        return None
    base = _python_module_base(root, mod)
    if base is None:
        return None
    code = (
        "import importlib, sys; "
        f"sys.path.insert(0, {str(base)!r}); "
        f"_o = importlib.import_module({mod!r}); "
    )
    o = "_o"
    for attr in obj_path.split("."):
        attr = attr.strip()
        if attr:
            code += f"{o} = getattr({o}, {attr!r}, None); "
    code += f"{o}()"
    return code


def _best_python_entry(project_dir, pdata: dict | None) -> str | None:
    """Pick the most likely Python entry file inside ``project_dir``.

    Honors an explicit ``[tool.mcp]`` marker, otherwise chooses the first
    matching common entry name actually present on disk.
    """
    pyproject_text = ""
    try:
        pyproject_text = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
    except Exception:
        pyproject_text = ""
    if "[tool.mcp]" in pyproject_text and "server" in pyproject_text:
        return "server.py"

    common = ("main.py", "server.py", "app.py", "cli.py", "mcp_server.py", "__main__.py")
    for name in common:
        if (project_dir / name).exists():
            return name
    try:
        for f in sorted(project_dir.glob("*.py")):
            return f.name
    except Exception:
        pass
    return None


def _pick_local_entry(tmp_dir) -> list[str] | None:
    """Heuristically pick the most likely MCP entry command from a clone.

    Order of preference (all paths resolved relative to ``tmp_dir``):

    Node:
      1. built output ``dist/index.js`` / ``build/index.js``
      2. ``package.json.bin`` entry point
      3. ``package.json.main`` / root ``index.js`` / ``src/index.js``
    Python:
      4. root ``server.py`` / ``main.py`` / ``mcp_server.py`` / ``app.py``
      5. ``pyproject.toml`` ``[tool.mcp.servers]`` declared command
      6. ``pyproject.toml`` ``[project.scripts]`` console entry →
         ``uv run --directory <project> <name>`` (auto-installs deps), else a
         ``python -c`` invocation of the declared ``module:obj.attr()``
      7. package ``__main__.py`` (flat or ``src/``) via ``runpy``
      8. recursive ``**/server.py`` / ``**/main.py`` (skips tool dirs)

    Returns ``None`` when nothing plausible is found.
    """
    import json

    from pathlib import Path as _P

    root = _P(tmp_dir)

    # ── Monorepo sub-project check ──────────────────────────────────────
    # If root itself has no manifest, but a subdirectory containing 'mcp' in its
    # name has a manifest (pyproject.toml/package.json), evaluate that first.
    if not (root / "package.json").exists() and not (root / "pyproject.toml").exists() and not (root / "go.mod").exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and "mcp" in child.name.lower():
                if (child / "pyproject.toml").exists() or (child / "package.json").exists():
                    sub_entry = _pick_local_entry(child)
                    if sub_entry:
                        if sub_entry[0] == "uv":
                            return sub_entry
                        res = []
                        for idx, token in enumerate(sub_entry):
                            if idx > 0 and not token.startswith("-") and (child / token).exists():
                                res.append(str((child / token).relative_to(root)))
                            else:
                                res.append(token)
                        return res

    # ── Node ─────────────────────────────────────────────────────────────
    for rel in ("dist/index.js", "build/index.js", "src/index.js", "index.js"):
        if (root / rel).exists():
            return ["node", rel]

    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            bin_entry = pkg.get("bin")
            if isinstance(bin_entry, dict):
                entry = next(iter(bin_entry.values()))
            elif isinstance(bin_entry, str):
                entry = bin_entry
            else:
                entry = None
            if entry and (root / entry).exists():
                return ["node", str(entry)]
            main = pkg.get("main")
            if main and (root / main).exists():
                return ["node", str(main)]
        except Exception:
            pass

    # ── Go ───────────────────────────────────────────────────────────────
    # Go projects use go.mod at the module root or in a subdirectory (e.g. whatsapp-bridge/).
    # Prefer an explicit cmd/ subdirectory (the conventional Go layout) or the module path.
    all_gomods = [root / "go.mod"] if (root / "go.mod").exists() else [
        f for f in sorted(root.rglob("go.mod"))
        if not any(part.startswith(".") or part in ("node_modules", "vendor", ".git") for part in f.relative_to(root).parts)
    ]
    if all_gomods:
        gomod = all_gomods[0]
        gdir = gomod.parent
        has_stdio_subcommand = False
        readme = ""
        try:
            readme = (root / "README.md").read_text(encoding="utf-8").lower()
        except Exception:
            pass
        if "stdio" in readme:
            has_stdio_subcommand = True
        else:
            for go_file in gdir.rglob("*.go"):
                try:
                    text = go_file.read_text(encoding="utf-8", errors="ignore").lower()
                    if "stdio" in text or "cobra" in text:
                        has_stdio_subcommand = True
                        break
                except Exception:
                    pass

        sub_args = ["stdio"] if has_stdio_subcommand else []

        cmd_dir = gdir / "cmd"
        if cmd_dir.is_dir():
            candidates = sorted(
                d for d in cmd_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            )
            for entry_dir in candidates:
                if (entry_dir / "main.go").exists():
                    rel_sub = entry_dir.relative_to(root)
                    return ["go", "run", f"./{rel_sub}"] + sub_args
        rel_gdir = gdir.relative_to(root)
        rel_str = f"./{rel_gdir}" if str(rel_gdir) != "." else "."
        return ["go", "run", rel_str] + sub_args

    # ── Python ───────────────────────────────────────────────────────────
    # Locate the project's pyproject.toml — it may live in a subdirectory
    # (e.g. lharries/whatsapp-mcp keeps the server in whatsapp-mcp-server/).
    pyproject = root / "pyproject.toml"
    project_dir = root
    if not pyproject.exists():
        # Search immediate subdirectories for the primary project root.
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and (
                "__pycache__" not in child.parts
            ):
                if (child / "pyproject.toml").exists():
                    pyproject = child / "pyproject.toml"
                    project_dir = child
                    break
    pdata: dict | None = None
    if pyproject.exists():
        try:
            import tomllib

            pdata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            pdata = None

    # If we have a pyproject.toml and uv is available, run the entry via
    # `uv run --directory` so the server's own deps (e.g. mcp 1.x / FastMCP)
    # are installed in isolation instead of using the backend's system
    # Python (which may ship an incompatible mcp version). ``--directory``
    # (not ``--project``) also changes the process CWD into the project —
    # required for entry files resolved relative to a nested project root.
    if pdata and shutil.which("uv"):
        scripts = (
            (pdata.get("project") or {}).get("scripts")
            or (pdata.get("project") or {}).get("gui-scripts")
            or {}
        )
        if scripts:
            name = next(iter(scripts.keys()))
            return ["uv", "run", "--directory", str(project_dir), str(name)]
        entry = _best_python_entry(project_dir, pdata)
        if entry:
            return ["uv", "run", "--directory", str(project_dir), "python", entry]

    # No uv available — best-effort fallbacks using the system Python.
    if pdata:
        scripts = (
            (pdata.get("project") or {}).get("scripts")
            or (pdata.get("project") or {}).get("gui-scripts")
            or {}
        )
        if scripts:
            entry = next(iter(scripts.values()))
            code = _python_console_entry_code(project_dir, entry)
            if code:
                return ["python", "-c", code]

    # [tool.mcp.servers] declared command — highest-authority Python signal.
    if pdata:
        tool_mcp = (pdata.get("tool") or {}).get("mcp", {}).get("servers", {})
        if tool_mcp:
            srv = next(iter(tool_mcp.values()), {})
            cmd = srv.get("command")
            if cmd:
                return [cmd] + list(srv.get("args") or [])[:2]

    # No uv / no pyproject — fall back to running with the system Python.
    for rel in ("server.py", "main.py", "mcp_server.py", "app.py"):
        if (root / rel).exists():
            return ["python", rel]

    # __main__.py inside a package dir (flat or src/) — run via runpy so the
    # package resolves without PYTHONPATH plumbing.
    for base in (root, root / "src"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name in (
                "__pycache__", ".git", "node_modules", ".venv", "venv",
            ):
                continue
            if (child / "__main__.py").exists():
                code = (
                    "import runpy, sys; "
                    f"sys.path.insert(0, {str(base)!r}); "
                    f"runpy.run_module({child.name!r}, run_name='__main__')"
                )
                return ["python", "-c", code]

    # Recursive fallback under src/ (or any layout) — skip tool/build dirs.
    for target in ("server.py", "mcp_server.py", "main.py"):
        for hit in sorted(root.rglob(target)):
            rel_parts = hit.relative_to(root).parts
            if any(p in ("__pycache__", ".git", "node_modules", ".venv", "venv") for p in rel_parts):
                continue
            rel = str(hit.relative_to(root))
            if rel != target:  # only add non-root hits (roots handled above)
                return ["python", rel]

    return None


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


def _sanitize_stdio_env(env: dict[str, str]) -> dict[str, str]:
    """Drop backend-virtualenv state that must not leak into spawned servers.

    The backend itself runs under ``uv run``, so ``os.environ`` carries
    ``VIRTUAL_ENV`` (uv then warns "does not match the project environment
    path" for every spawned server) and potentially ``PYTHON*`` variables
    whose paths could shadow the server's own dependencies. Venv ``bin``
    entries on ``PATH`` are dropped too; system paths (and ``uv`` itself)
    remain resolvable.
    """
    from pathlib import Path

    stray_keys = {"VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE"}
    cleaned = {k: v for k, v in env.items() if k not in stray_keys}
    path = cleaned.get("PATH")
    if path:
        kept = [p for p in path.split(os.pathsep) if p and ".venv" not in Path(p).parts]
        cleaned["PATH"] = os.pathsep.join(kept)
    return cleaned


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
    env = _sanitize_stdio_env({**os.environ})
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
        if "GITHUB_TOKEN" in env and "GITHUB_PERSONAL_ACCESS_TOKEN" not in env:
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = env["GITHUB_TOKEN"]
        elif "GITHUB_PERSONAL_ACCESS_TOKEN" in env and "GITHUB_TOKEN" not in env:
            env["GITHUB_TOKEN"] = env["GITHUB_PERSONAL_ACCESS_TOKEN"]

    client_id = env.get("CLIENT_ID") or env.get("GOOGLE_CLIENT_ID") or env.get("GMAIL_CLIENT_ID") or env.get("OAUTH_CLIENT_ID")
    client_secret = env.get("CLIENT_SECRET") or env.get("GOOGLE_CLIENT_SECRET") or env.get("GMAIL_CLIENT_SECRET") or env.get("OAUTH_CLIENT_SECRET")
    refresh_token = env.get("REFRESH_TOKEN") or env.get("GOOGLE_REFRESH_TOKEN") or env.get("GMAIL_REFRESH_TOKEN")
    access_token = env.get("ACCESS_TOKEN") or env.get("GOOGLE_ACCESS_TOKEN") or env.get("GMAIL_ACCESS_TOKEN")

    # Inject universal uppercase env variable aliases so any standard server finds them
    if client_id:
        env.setdefault("CLIENT_ID", client_id)
        env.setdefault("GOOGLE_CLIENT_ID", client_id)
        env.setdefault("GMAIL_CLIENT_ID", client_id)
        env.setdefault("OAUTH_CLIENT_ID", client_id)
    if client_secret:
        env.setdefault("CLIENT_SECRET", client_secret)
        env.setdefault("GOOGLE_CLIENT_SECRET", client_secret)
        env.setdefault("GMAIL_CLIENT_SECRET", client_secret)
        env.setdefault("OAUTH_CLIENT_SECRET", client_secret)

    cmd_binary, cmd_args, cwd = await _prepare_local_repo_stdio(command, source_repo_url)

    # Generic OAuth file provisioning: if OAuth credentials are provided for a stdio server,
    # generate standard OAuth key/credential JSON files in both cwd and home config dirs,
    # and map standard environment variable aliases to those file paths.
    if client_id or client_secret or refresh_token or access_token:
        import hashlib
        import json
        from pathlib import Path

        oauth_json_data = {
            "installed": {
                "client_id": client_id or "",
                "client_secret": client_secret or "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost:3000/oauth2callback"],
            },
            "web": {
                "client_id": client_id or "",
                "client_secret": client_secret or "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost:3000/oauth2callback"],
            },
        }

        # Provision in server working directory (cwd)
        cwd_path = Path(cwd) if cwd else Path.cwd()
        cwd_oauth_file = cwd_path / "gcp-oauth.keys.json"
        cwd_creds_file = cwd_path / "credentials.json"

        if client_id and client_secret and not cwd_oauth_file.exists():
            cwd_oauth_file.write_text(json.dumps(oauth_json_data, indent=2), encoding="utf-8")

        if (refresh_token or access_token) and not cwd_creds_file.exists():
            creds_data = {
                "access_token": access_token or "placeholder_token",
                "refresh_token": refresh_token or "",
                "token_type": "Bearer",
            }
            cwd_creds_file.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")

        # Provision in standard user home config locations
        home = Path.home()
        for conf_dir in (home / ".gmail-mcp", home / ".config" / "google-drive-mcp", home / ".mcp"):
            conf_dir.mkdir(parents=True, exist_ok=True)
            o_file = conf_dir / "gcp-oauth.keys.json"
            c_file = conf_dir / "credentials.json"
            if client_id and client_secret and not o_file.exists():
                o_file.write_text(json.dumps(oauth_json_data, indent=2), encoding="utf-8")
            if (refresh_token or access_token) and not c_file.exists():
                creds_data = {
                    "access_token": access_token or "placeholder_token",
                    "refresh_token": refresh_token or "",
                    "token_type": "Bearer",
                }
                c_file.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")

        # Map standard environment variables to generated file paths
        target_oauth_path = str(cwd_oauth_file if cwd_oauth_file.exists() else home / ".gmail-mcp" / "gcp-oauth.keys.json")
        target_creds_path = str(cwd_creds_file if cwd_creds_file.exists() else home / ".gmail-mcp" / "credentials.json")

        env.setdefault("GMAIL_OAUTH_PATH", target_oauth_path)
        env.setdefault("GOOGLE_DRIVE_OAUTH_CREDENTIALS", target_oauth_path)
        env.setdefault("OAUTH_KEYS_PATH", target_oauth_path)
        env.setdefault("GCP_OAUTH_KEYS_PATH", target_oauth_path)
        env.setdefault("GMAIL_CREDENTIALS_PATH", target_creds_path)
        env.setdefault("CREDENTIALS_PATH", target_creds_path)

    logger.info(
        "starting_mcp_stdio",
        command=cmd_binary,
        args=cmd_args,
        cwd=cwd,
        env_keys=list(env.keys()),
    )

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
