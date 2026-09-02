"""Universal repository analyzer for MCP servers.

Detects transport type, runtime, command, remote endpoints, and required environment
variables in zero-hardcoded-rules manner.

Supports: GitHub (local clone or API), remote HTTP endpoints, local files.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from github import Auth, Github
from httpx import AsyncClient
import tomllib
from urllib.parse import urlparse

from vendor_resources.schemas import (
    AnalyzeRepoResponse,
    McpDetectRequest,
    McpDetectResponse,
)
import structlog

logger = structlog.get_logger(__name__)


# Registry of runtime manifest scanners (decoupled, pluggable)
_SCANNERS = {
    "github": lambda path, root: _scan_github_repo(path, root),
    "remote_http": lambda path, root: _scan_remote_http(path, root),
    "local_file": lambda path, root: _scan_local_file(path, root),
}


async def analyze_repo(repo_url: str) -> AnalyzeRepoResponse:
    """Universal analyzer that detects MCP server characteristics.

    Supports GitHub repositories (URL or local path) and direct HTTP endpoints.
    Detects transport, runtime, command, remote URLs, and required env vars.
    """
    parsed = urlparse(repo_url)
    root = Path("/tmp/repo_analysis")

    if "github.com" in repo_url:
        return await _analyze_github_repo(repo_url, parsed, root)

    if parsed.scheme in ("http", "https"):
        return await _analyze_remote_http(repo_url, parsed, root)

    return await _analyze_local_path(repo_url, parsed, root)


def _best_python_entry(
    pyproject_content: str,
    requirements_content: str,
    python_files: list[str] | None,
) -> str:
    """Pick the most likely Python entry file.

    Honors an explicit marker if present, otherwise picks the first matching
    common entry name from the actual files in the repo (so we report the real
    ``main.py`` rather than a guessed ``server.py``).
    """
    if "[tool.mcp]" in pyproject_content and "server" in pyproject_content:
        return "server.py"

    common_names = ("main.py", "server.py", "app.py", "cli.py", "mcp_server.py", "__main__.py")
    files = python_files or []
    for name in common_names:
        if name in files:
            return name
    if files:
        return files[0]
    if requirements_content:
        return "mcp_server.py"
    return "server.py"




def _infer_transport_and_runtime(
    scanned: dict[str, Any],
) -> tuple[str, str, str | None, str | None]:
    """Convert scanned manifests into transport/runtime/command.

    Deterministic heuristic with zero hardcoded vendor rules.
    Handles both parsed dict objects and raw string content.
    """
    transport = "stdio"
    runtime = "custom"
    command = None
    remote_endpoint = None

    def get_content(key: str) -> str:
        """Extract string content from scanned dict, handling both raw strings and parsed dicts."""
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            # Try to extract meaningful string from dict
            return str(val)
        return ""

    # Manifest-first preference (Node, Python, Go, Rust, Docker)
    if get_content("package.json"):
        transport = "stdio"
        runtime = "node"
        pkg_content = get_content("package.json")
        import json
        try:
            pkg = json.loads(pkg_content) if isinstance(pkg_content, str) else pkg_content
            pkg_name = pkg.get("name")
            pkg_bin = pkg.get("bin")
            if pkg_name and pkg_bin:
                # Package declares a published CLI entry point → install & run.
                command = f"npx -y {pkg_name}"
            elif pkg_name:
                # Name exists but no bin field — NOT safely runnable via npx
                # (the package may not be published). Run from source; the
                # connect layer clones source_repo_url first.
                main = pkg.get("main") or "index.js"
                command = f"node {main}"
            else:
                script = pkg.get("scripts", {}).get("start") or pkg.get("scripts", {}).get("dev")
                command = f"npm start" if script else "node index.js"
        except (json.JSONDecodeError, AttributeError):
            command = "npm start"

    elif get_content("pyproject.toml") or get_content("requirements.txt"):
        transport = "stdio"
        runtime = "python"
        pyproject_content = get_content("pyproject.toml")
        # Prefer the real entry file if we know which .py files exist.
        entry = _best_python_entry(
            pyproject_content, get_content("requirements.txt"), scanned.get("python_files")
        )
        command = f"python {entry}"

    elif get_content("go.mod"):
        transport = "stdio"
        runtime = "go"
        gomod_content = get_content("go.mod")
        module_match = re.search(r"module\s+(\S+)", gomod_content)
        module = module_match.group(1) if module_match else "."
        command = f"go run ./{module}"

    elif get_content("Cargo.toml"):
        transport = "stdio"
        runtime = "rust"
        command = "cargo run --bin mcp-server"

    elif get_content("dockerfile") or get_content("Dockerfile"):
        transport = "docker"
        runtime = "docker"
        command = "docker run --rm -i mcp-server"

    elif get_content("docker-compose.yml") or get_content("docker-compose.yaml"):
        transport = "docker"
        runtime = "docker"
        command = "docker-compose up -d"

    elif get_content("pyproject.toml"):
        transport = "stdio"
        runtime = "python"
        entry = "server.py"
        pyproject_content = get_content("pyproject.toml")
        # Check for mcp server marker in content
        if "[tool.mcp]" in pyproject_content and "server" in pyproject_content:
            entry = "server.py"
        elif get_content("requirements.txt"):
            entry = "mcp_server.py"
        command = f"python /app/{entry}"

    elif get_content("go.mod"):
        transport = "stdio"
        runtime = "go"
        gomod_content = get_content("go.mod")
        # Extract module name from go.mod
        module_match = re.search(r"module\s+(\S+)", gomod_content)
        module = module_match.group(1) if module_match else "."
        command = f"cd /app && go run ./{module}"

    elif get_content("Cargo.toml"):
        transport = "stdio"
        runtime = "rust"
        command = "cd /app && cargo run --bin mcp-server"

    elif get_content("README.md"):
        readme = get_content("README.md")
        # Extract remote HTTP(S) endpoint with /mcp, /sse or /stream path
        # suffix. Match whole URLs, then require the MCP suffix — the old
        # alternation could match a bare "/sse" on its own. A GitHub
        # repository URL is never a remote endpoint — filter it out.
        urls = [
            u.rstrip(".,;:()\"'`")
            for u in re.findall(r"https?://[^\s'\"'`]+", readme)
            if re.search(r"/(?:mcp|sse|stream)$", u.rstrip(".,;:()\"'`"))
            and urlparse(u).hostname not in ("github.com", "www.github.com")
        ]
        if urls:
            remote_endpoint = urls[0]
            transport = "streamable_http"
            runtime = "remote"
            command = None
        # Check for container instructions
        if any(kw in readme.lower() for kw in ["docker", "container", "compose"]):
            runtime = "docker"
            transport = "docker"

    # Fallback to explicit remote endpoint pattern
    manifest_content = get_content("manifest")
    if not remote_endpoint and "://" in manifest_content:
        candidate = manifest_content.strip()
        if urlparse(candidate).hostname not in ("github.com", "www.github.com"):
            remote_endpoint = candidate
            transport = "streamable_http"
            runtime = "remote"

    return transport, runtime, command, remote_endpoint


async def _fetch_github_raw_manifests(owner: str, repo: str) -> dict[str, Any]:
    """Fetch repository manifest files over HTTPS raw API when git binary is not installed."""
    files_to_check = [
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
        "go.mod",
        "Cargo.toml",
        "README.md",
        ".env.example",
    ]
    scanned: dict[str, Any] = {}
    async with AsyncClient(follow_redirects=True, timeout=10.0) as client:
        for fname in files_to_check:
            for branch in ("main", "master", "HEAD"):
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{fname}"
                try:
                    res = await client.get(raw_url)
                    if res.status_code == 200:
                        scanned[fname] = res.text
                        break
                except Exception:
                    pass
    return scanned


async def _analyze_github_repo(url: str, parsed, root: Path) -> AnalyzeRepoResponse:
    """Clone or probe a GitHub repo for MCP server characteristics.

    Shallow clone (--depth 1) for speed; fallback to HTTP raw manifest fetch or GitHub API.
    """
    logger.info("analyzing_github_repo", repo_url=url)
    scanned: dict[str, Any] = {}

    import re
    import shutil
    import subprocess

    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", url)
    owner, repo_name = match.groups() if match else ("unknown", "unknown")

    # Try shallow clone first if git binary is present
    git_bin = shutil.which("git")
    cloned_successfully = False

    if git_bin and url.startswith("https://github.com/"):
        try:
            repo_path = f"{owner}_{repo_name}".replace("/", "_")
            clone_dir = root / repo_path

            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)

            # Always clone the canonical repo URL — the raw input may contain
            # a sub-path (e.g. .../tree/main/src/filesystem) which git rejects.
            canonical_url = f"https://github.com/{owner}/{repo_name}"
            subprocess.run(
                [
                    git_bin,
                    "clone",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    canonical_url,
                    str(clone_dir),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )

            scanned = await _scan_local_dir(clone_dir)
            shutil.rmtree(clone_dir, ignore_errors=True)
            cloned_successfully = True
        except Exception as exc:
            logger.warning("git_clone_failed_fallback_to_raw_fetch", repo_url=url, error=str(exc))

    if not cloned_successfully and owner != "unknown":
        # Fallback to direct raw HTTPS manifest fetching
        scanned = await _fetch_github_raw_manifests(owner, repo_name)

    # Detect transport/runtime
    transport, runtime, command, remote_endpoint = _infer_transport_and_runtime(scanned)

    # The server may live in a nested subdirectory (e.g. whatsapp-mcp keeps it
    # in whatsapp-mcp-server/). Prefix the command so it runs from the right
    # directory — _pick_local_entry will later resolve the exact entry file.
    subdir = scanned.get("_server_subdir")
    if subdir and command and not command.startswith("docker"):
        command = f"{subdir}/{command}"

    # Extract required environment variables
    required_env_vars = _extract_env_vars(scanned)

    # Determine auth type based on detected patterns
    auth_type = _detect_auth_type(scanned, remote_endpoint)

    # If suggested command is still unknown, fall back to a source-based
    # entry (the connect layer clones source_repo_url and cd's into it).
    if not command and runtime == "node":
        command = f"{subdir}/node index.js" if subdir else "node index.js"
    elif not command and runtime == "python":
        command = f"{subdir}/python server.py" if subdir else "python server.py"
    elif not command:
        # No manifest found at all — best-effort stdio entry. A GitHub URL
        # must never be stored as a remote endpoint.
        command = f"{subdir}/python server.py" if subdir else "python server.py"

    return AnalyzeRepoResponse(
        detected=True,
        transport=transport,
        runtime=runtime,
        suggested_command=command,
        remote_endpoint=remote_endpoint,
        required_env_vars=required_env_vars,
        auth_type=auth_type,
        hints=[],
    )


async def _analyze_remote_http(url: str, parsed, root: Path) -> AnalyzeRepoResponse:
    """Probes a remote HTTP endpoint for MCP server characteristics."""
    logger.info("analyzing_remote_http", endpoint=url)

    try:
        async with AsyncClient(follow_redirects=True, timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 404:
                raise ValueError("Endpoint not found")

            # Try to fetch MCP initialization endpoint
            mcp_init = url.rstrip("/") + "/mcp"
            mcp_response = await client.post(
                mcp_init, json={"method": "initialize", "params": {}, "id": 1}
            )

            if mcp_response.status_code == 200:
                transport = "streamable_http"
                runtime = "remote"
                remote_endpoint = url.rstrip("/") + "/mcp"
                command = None
            else:
                # Check for SSE endpoint
                sse_endpoint = url.rstrip("/") + "/sse"
                sse_response = await client.get(sse_endpoint)
                if sse_response.status_code == 200:
                    transport = "sse"
                    runtime = "remote"
                    remote_endpoint = sse_endpoint
                    command = None
                else:
                    # Default to stdio with HTTP transport hint
                    transport = "stdio"
                    runtime = "custom"
                    remote_endpoint = url
                    command = None

            required_env_vars = _extract_env_vars({"manifest": url})
            auth_type = _detect_auth_type({"manifest": url}, url)

            return AnalyzeRepoResponse(
                detected=True,
                transport=transport,
                runtime=runtime,
                suggested_command=command,
                remote_endpoint=remote_endpoint,
                required_env_vars=required_env_vars,
                auth_type=auth_type,
                hints=["Remote HTTP endpoint probed"],
            )

    except Exception as exc:
        logger.exception("remote_http_analysis_failed", endpoint=url)
        return AnalyzeRepoResponse(
            detected=False,
            transport="unknown",
            runtime="unknown",
            suggested_command=None,
            remote_endpoint=None,
            required_env_vars=[],
            auth_type="unknown",
            hints=[
                f"Failed to probe HTTP endpoint: {str(exc)}",
                "Ensure the endpoint is reachable and supports MCP protocol",
            ],
        )


async def _analyze_local_path(path: str, parsed, root: Path) -> AnalyzeRepoResponse:
    """Analyzes a local file system path for MCP server characteristics."""
    logger.info("analyzing_local_path", path=path)

    local_path = Path(path)
    if not local_path.exists():
        return AnalyzeRepoResponse(
            detected=False,
            transport="unknown",
            runtime="unknown",
            suggested_command=None,
            remote_endpoint=None,
            required_env_vars=[],
            auth_type="unknown",
            hints=[f"Local path does not exist: {path}"],
        )

    # For local paths, treat as directory
    if local_path.is_dir():
        scanned = await _scan_local_dir(local_path)
    else:
        scanned = await _scan_local_file(local_path)

    transport, runtime, command, remote_endpoint = _infer_transport_and_runtime(scanned)
    required_env_vars = _extract_env_vars(scanned)
    auth_type = _detect_auth_type(scanned, remote_endpoint)

    return AnalyzeRepoResponse(
        detected=True,
        transport=transport,
        runtime=runtime,
        suggested_command=command,
        remote_endpoint=remote_endpoint,
        required_env_vars=required_env_vars,
        auth_type=auth_type,
        hints=["Local directory analyzed"],
    )


async def _scan_local_dir(dir_path: Path) -> dict[str, Any]:
    """Scan a local directory for MCP server manifests.

    Scans the top level first, then — if no manifests are found there —
    drills into the immediate subdirectory that carries the most manifest
    files (repos like lharries/whatsapp-mcp keep the server in a nested
    ``whatsapp-mcp-server/`` dir). The chosen subdirectory is scanned as if
    it were the repo root so command/env detection resolve real paths.
    """
    scanned: dict[str, Any] = {}

    manifest_names = {
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "go.mod",
        "Cargo.toml",
        "README.md",
        ".env.example",
        ".env",
    }

    async def _scan_dir(d: Path) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for marker in manifest_names:
            fp = d / marker
            if fp.exists():
                out[marker] = await _read_file_safely(fp)
        python_files = [f.name for f in sorted(d.glob("*.py"))[:5]]
        if python_files:
            out["python_files"] = python_files
        return out

    scanned = await _scan_dir(dir_path)

    # No *build* manifests at the top level (a lone README.md doesn't count)
    # — look one level down for the primary server directory and rescan.
    build_manifests = (
        "package.json", "pyproject.toml", "requirements.txt",
        "go.mod", "Cargo.toml", "Dockerfile",
    )
    has_build_manifest = any(m in scanned for m in build_manifests)
    if not has_build_manifest:
        best_dir: Path | None = None
        best_count = 0
        try:
            for child in sorted(dir_path.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                count = sum(1 for m in manifest_names if (child / m).exists())
                count += len(list(child.glob("*.py")))
                if count > best_count:
                    best_count = count
                    best_dir = child
        except PermissionError:
            pass
        if best_dir is not None:
            scanned = await _scan_dir(best_dir)
            scanned["_server_subdir"] = best_dir.name

    return scanned


async def _scan_local_file(file_path: Path) -> dict[str, Any]:
    """Scan a single file for MCP server characteristics."""
    scanned = {}
    suffix = file_path.suffix.lower()

    if suffix == ".json":
        scanned["json_file"] = await _read_file_safely(file_path)
    elif suffix == ".toml":
        scanned["toml_file"] = await _read_file_safely(file_path)
    elif suffix == ".md":
        scanned["README.md"] = await _read_file_safely(file_path)
    else:
        scanned["other"] = file_path.name

    return scanned


async def _scan_github_tree(items, root: Path) -> dict[str, Any]:
    """Recursively scan GitHub repository tree for MCP server manifests."""
    scanned = {}

    def process_item(item):
        if item.type == "file":
            name = item.name
            if name in [
                "Dockerfile",
                "docker-compose.yml",
                "docker-compose.yaml",
                "package.json",
                "pyproject.toml",
                "requirements.txt",
                "setup.py",
                "setup.cfg",
                "go.mod",
                "Cargo.toml",
                "README.md",
                ".env.example",
                ".env",
            ]:
                if not scanned.get(name):
                    scanned[name] = item.download_url
            elif name.endswith(".py"):
                if "python_files" not in scanned:
                    scanned["python_files"] = []
                scanned["python_files"].append(name)
        elif item.type == "dir":
            # Recursively process directories
            for subitem in item.contents:
                process_item(subitem)

    for item in items:
        process_item(item)

    # Download actual file contents for scanned manifests
    for key in list(scanned.keys()):
        if key in ["Dockerfile", "docker-compose.yml", "docker-compose.yaml", "package.json", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "go.mod", "Cargo.toml", "README.md", ".env.example", ".env"]:
            try:
                file_content = item.download_url  # This is a URL
                # We can't easily download from GitHub API tree without making actual HTTP requests
                # For simplicity, we'll skip detailed content parsing for now
                scanned[key] = f"<URL: {file_content}>"
            except Exception as e:
                scanned[key] = f"<Download error: {str(e)}>"

    return scanned


async def _scan_github_repo(url: str, root: Path) -> dict[str, Any]:
    """Legacy method - use _analyze_github_repo directly."""
    logger.warning("Using deprecated _scan_github_repo method")
    return {}


IGNORED_SYSTEM_ENV_VARS = {
    "NODE_PATH",
    "PYTHONPATH",
    "PATH",
    "NODE_ENV",
    "PYTHONUNBUFFERED",
    "HOME",
    "PORT",
    "HOST",
    "PWD",
    "SHELL",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "DOCKER_HOST",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "CI",
    "DEBUG",
}

# Generic secret-style env var key shapes. No provider names — anything
# ending in one of these suffixes (e.g. ``FOO_TOKEN``, ``BAR_PAT``,
# ``BAZ_CLIENT_ID``) is treated as a credential the server declares.
_CREDENTIAL_ENV_KEY_RE = re.compile(
    r"\b([A-Z0-9_]{2,}_(?:TOKEN|KEY|SECRET|PASSWORD|AUTH|API|ID|URL|PAT|CLIENT_ID|ACCESS_KEY))\b",
    re.IGNORECASE,
)
# Same shape, but only when followed by ``=`` (an explicit declaration).
_CREDENTIAL_ENV_DECL_RE = re.compile(
    r"(?:export\s+)?([A-Za-z0-9_]{2,}_(?:TOKEN|KEY|SECRET|PASSWORD|AUTH|API|ID|URL|PAT|CLIENT_ID|ACCESS_KEY))=",
    re.IGNORECASE,
)


def _extract_env_vars(scanned: dict[str, Any]) -> list[str]:
    """Extract required environment variables from scanned manifests.

    Scans .env files and README documentation for required secret credential keys,
    automatically filtering out system/runtime environment variables like NODE_PATH.
    """
    env_vars = set()

    def get_content(key: str) -> str:
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            return str(val)
        return ""

    # Scan .env files (with and without leading dot)
    for env_file in ["env", "env.example", ".env", ".env.example"]:
        content = get_content(env_file)
        if content:
            for m in _CREDENTIAL_ENV_KEY_RE.findall(content):
                m_upper = m.upper()
                if m_upper not in IGNORED_SYSTEM_ENV_VARS:
                    env_vars.add(m_upper)

    # Scan documentation for explicit credential declarations (``FOO_KEY=``,
    # ``export FOO_TOKEN=``, ``foo_pat=`` … case-insensitive).
    for key in ["manifest", "README.md"]:
        content = get_content(key)
        if content:
            for m in _CREDENTIAL_ENV_DECL_RE.findall(content):
                m_upper = m.upper()
                if m_upper not in IGNORED_SYSTEM_ENV_VARS:
                    env_vars.add(m_upper)

    # Filter out system runtime variables and auto-managed OAuth runtime tokens
    cleaned = []
    for v in env_vars:
        if v in IGNORED_SYSTEM_ENV_VARS:
            continue
        # OAuth runtime tokens are generated automatically via client_credentials / auth code exchange
        if v.endswith("_REFRESH_TOKEN") or v.endswith("_ACCESS_TOKEN") or v.endswith("_EXPIRES_IN"):
            continue
        cleaned.append(v)

    return sorted(cleaned)


def _detect_auth_type(scanned: dict[str, Any], remote_endpoint: str | None = None) -> str:
    """Detect authentication type based on what the server itself documents.

    Returns one of: none, api_key, bearer, basic, oauth2, env.

    ``remote_endpoint`` is intentionally ignored: an endpoint's auth scheme
    can never be inferred from its hostname (the same literal domain name
    can serve services with entirely different auth requirements), so nothing
    is guessed from URL patterns. Every classification comes from signals the
    server itself advertises — manifest/README mentions of bearer / API-key /
    OAuth / basic auth, and the credential-style environment variables it
    declares in ``.env*``.
    """
    def get_content(key: str) -> str:
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            return str(val)
        return ""

    # Generic credential-env check: any declared secret-style env var (from
    # .env* or documentation) signals env-based auth when nothing stronger
    # is documented. No provider names are consulted.
    hints = ["env_detected"] if _extract_env_vars(scanned) else []

    # Check for authentication hints in manifests
    for key in ["manifest", "README.md", "package.json"]:
        content = get_content(key)
        if content:
            if "Bearer" in content or "bearer" in content.lower():
                hints.append("bearer_detected")
            if "api_key" in content.lower() or "api-key" in content.lower() or "x-api-key" in content.lower():
                hints.append("api_key_detected")
            if "oauth" in content.lower():
                hints.append("oauth_detected")
            if "basic auth" in content.lower() or "authorization: basic" in content.lower():
                hints.append("basic_detected")

    # Determine based on heuristics
    if any("bearer" in h.lower() for h in hints):
        return "bearer"
    if any("api_key" in h.lower() for h in hints):
        return "api_key"
    if any("oauth" in h.lower() for h in hints):
        return "oauth2"
    if any("basic" in h.lower() for h in hints):
        return "basic"
    if any("env" in h.lower() for h in hints):
        return "env"

    # Default to none for local servers or when no auth hints found
    return "none"


async def _read_file_safely(file_path: Path) -> str:
    """Safely read file contents with error handling."""
    try:
        if file_path.exists():
            content = await asyncio.to_thread(file_path.read_text)
            return content[:10000]  # Limit to 10KB to avoid huge files
        return ""
    except Exception as exc:
        logger.debug("Failed to read file", path=str(file_path), error=str(exc))
        return ""


__all__ = [
    "analyze_repo",
]
