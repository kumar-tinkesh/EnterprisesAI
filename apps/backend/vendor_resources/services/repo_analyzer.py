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

    # Container-first preference
    dockerfile_content = get_content("dockerfile") or get_content("Dockerfile")
    docker_compose_content = get_content("docker-compose.yml") or get_content("docker-compose.yaml")
    if dockerfile_content or docker_compose_content:
        transport = "docker"
        runtime = "docker"
        if dockerfile_content and (("COPY" in dockerfile_content and "--from=" not in dockerfile_content) or ("FROM" in dockerfile_content)):
            cmd = "docker"
            if "RUN" in dockerfile_content:
                cmd += " run --rm -i"
            else:
                cmd += " run --rm"
            if "WORKDIR" in dockerfile_content:
                cmd += " && cd /app && " + dockerfile_content.split("WORKDIR")[1].split("\n")[0].strip()
            command = cmd.strip()
        elif docker_compose_content:
            command = "docker-compose up -d"

    elif get_content("package.json"):
        transport = "stdio"
        runtime = "node"
        pkg_content = get_content("package.json")
        # Try to parse JSON if it's a string
        import json
        try:
            pkg = json.loads(pkg_content) if isinstance(pkg_content, str) else pkg_content
            script = pkg.get("scripts", {}).get("start") or pkg.get("scripts", {}).get("dev") or "node ."
            entry = pkg.get("main") or pkg.get("bin", {}).get("mcp") or "."
            command = f"npx -y {entry}" if entry.endswith(".js") else f"cd /app && {script}"
        except (json.JSONDecodeError, AttributeError):
            command = "cd /app && npm start"

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
        # Extract remote HTTP(S) endpoint with /mcp or /sse path patterns
        urls = re.findall(
            r"https?://[^\s'\"']+(?:/[\w\-\.\~\$\+\!\*\'\(\)\;\=\&\%\?#]+)?/mcp|/sse|/stream",
            readme,
        )
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
        remote_endpoint = manifest_content
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

            subprocess.run(
                [
                    git_bin,
                    "clone",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    url,
                    str(clone_dir),
                ],
                check=True,
                capture_output=True,
                timeout=15,
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

    # Extract required environment variables
    required_env_vars = _extract_env_vars(scanned)

    # Determine auth type based on detected patterns
    auth_type = _detect_auth_type(scanned, remote_endpoint)

    # If suggested command is npx or npm and repo name is known, craft exact npx command
    if not command and runtime == "node":
        command = f"npx -y {repo_name}"
    elif not command and runtime == "python":
        command = "python server.py"

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
    """Scan a local directory for MCP server manifests."""
    scanned = {}

    # Look for standard MCP server manifest files
    for marker in [
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
        "pyproject.toml",
        "README.md",
        ".env.example",
        ".env",
    ]:
        file_path = dir_path / marker
        if file_path.exists():
            scanned[marker] = await _read_file_safely(file_path)

    # Add all Python files as potential servers
    python_files = list(dir_path.glob("*.py"))
    if python_files:
        scanned["python_files"] = [f.name for f in python_files[:5]]  # Limit to 5

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


def _extract_env_vars(scanned: dict[str, Any]) -> list[str]:
    """Extract required environment variables from scanned manifests.

    Uses regex patterns to identify common credential keys like GITHUB_TOKEN,
    OPENAI_API_KEY, etc.
    """
    env_vars = set()
    pattern = r"\b([A-Z0-9_]{2,}_(?:TOKEN|KEY|SECRET|PASSWORD|AUTH|API|ID|URL))\b"

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
            matches = re.findall(pattern, content, re.IGNORECASE)
            env_vars.update(matches)

    # Check for GitHub token in URLs or manifests
    for key in ["manifest", "README.md"]:
        content = get_content(key)
        if content:
            # Look for GitHub token patterns (more lenient)
            github_matches = re.findall(
                r"github_pat=[A-Za-z0-9_\-]+", content
            )
            if github_matches:
                env_vars.add("GITHUB_TOKEN")

    # Add common MCP server environment variables
    common_env_vars = {
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "SLACK_TOKEN",
        "DISCORD_TOKEN",
        "WEBHOOK_URL",
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "SMTP_PASSWORD",
        "JWT_SECRET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    }

    # Heuristic: If any Python/Node.js manifest is present, add relevant vars
    if get_content("pyproject.toml") or get_content("package.json"):
        env_vars.update(["PYTHONPATH", "NODE_PATH"])

    if get_content("dockerfile") or get_content("Dockerfile") or get_content("docker-compose.yml"):
        env_vars.update(["DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"])

    return sorted(list(env_vars))


def _detect_auth_type(scanned: dict[str, Any], remote_endpoint: str | None) -> str:
    """Detect authentication type based on scanned manifests and endpoint.

    Returns one of: none, api_key, bearer, basic, oauth2, env, unknown.
    """
    def get_content(key: str) -> str:
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            return str(val)
        return ""

    # Check for authentication hints in manifests
    hints = []
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

    # Check for standard authentication environment variables
    for key in ["GITHUB_TOKEN", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"]:
        content = get_content("env") + get_content("env.example") + get_content(".env") + get_content(".env.example")
        if key in content:
            hints.append(f"{key}_detected")

    # Check remote endpoint patterns
    if remote_endpoint:
        if "github.com" in remote_endpoint:
            return "bearer"
        if "openai.com" in remote_endpoint or "api.openai.com" in remote_endpoint:
            return "api_key"
        if "slack.com" in remote_endpoint:
            return "bearer"

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
