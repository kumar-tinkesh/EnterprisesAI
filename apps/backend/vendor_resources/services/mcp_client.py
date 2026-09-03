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

                # Determine entry executable (robust — searches beyond the
                # obvious root files, covers pyproject console scripts etc).
                found = _pick_local_entry(tmp_dir)
                if found:
                    parts = found
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed_to_prepare_local_repo %s: %s", git_url, exc)

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
         ``uv run --project <repo> <name>`` (auto-installs deps), else a
         ``python -c`` invocation of the declared ``module:obj.attr()``
      7. package ``__main__.py`` (flat or ``src/``) via ``runpy``
      8. recursive ``**/server.py`` / ``**/main.py`` (skips tool dirs)

    Returns ``None`` when nothing plausible is found.
    """
    import json

    from pathlib import Path as _P

    root = _P(tmp_dir)

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
    # `uv run --project` so the server's own deps (e.g. mcp 1.x / FastMCP)
    # are installed in isolation instead of using the backend's system
    # Python (which may ship an incompatible mcp version).
    if pdata and shutil.which("uv"):
        scripts = (
            (pdata.get("project") or {}).get("scripts")
            or (pdata.get("project") or {}).get("gui-scripts")
            or {}
        )
        if scripts:
            name = next(iter(scripts.keys()))
            return ["uv", "run", "--project", str(project_dir), str(name)]
        entry = _best_python_entry(project_dir, pdata)
        if entry:
            return ["uv", "run", "--project", str(project_dir), "python", entry]

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

