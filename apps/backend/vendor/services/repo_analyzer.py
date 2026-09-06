"""Universal repository analyzer for MCP servers.

Detects transport type, runtime, command, remote endpoints, and required environment
variables with confidence scoring and normalized output.

Supports: GitHub (local clone or API), remote HTTP endpoints, local files.

Section 15 confidence scale:
  0.95–1.00  Very strong  (StdioServerTransport / StreamableHTTPTransport in source code)
  0.80–0.94  Strong       (README explicitly says stdio / streamable_http)
  0.60–0.79  Medium       (package.json / pyproject.toml / go.mod runtime hints)
  0.40–0.59  Weak         (docker-compose / CLI --help pattern)
  <0.40      Unknown
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from github import Auth, Github
from httpx import AsyncClient
import tomllib
from urllib.parse import urlparse

from vendor.api.v1.schemas import (
    AnalyzeRepoResponse,
    McpDetectRequest,
    McpDetectResponse,
)
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses for normalized output (Section 19 / Section 15 of the arch doc)
# ---------------------------------------------------------------------------

@dataclass
class TransportEvidence:
    """A single piece of evidence supporting a transport classification."""
    source: str   # e.g. "README", "source_code", "package.json"
    reason: str   # human-readable explanation

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "reason": self.reason}


@dataclass
class AuthField:
    """Describes one field the UI should render when collecting credentials (Section 11)."""
    name: str
    label: str
    type: str = "secret"        # "secret" | "text" | "url"
    required: bool = True
    location: str = "env"       # "env" | "header" | "query"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "location": self.location,
        }


@dataclass
class NormalizedMCPConfig:
    """Fully normalized MCP server configuration (Section 19 of the arch doc).

    All fields are JSON-serializable so the dict representation can be stored
    directly in ``VendorMCPServer.auth_schema`` / ``transport_evidence`` etc.
    """
    # --- source ---
    source_type: str = "github"          # "github" | "remote" | "local"
    source_url: str = ""
    source_repo: str = ""                # "owner/repo"
    source_branch: str = "main"
    source_subpath: str | None = None

    # --- transport (with evidence) ---
    transport_type: str = "unknown"
    transport_confidence: float = 0.0
    transport_evidence: list[TransportEvidence] = field(default_factory=list)

    # --- runtime ---
    runtime_type: str = "unknown"

    # --- startup ---
    command: str | None = None
    args: list[str] = field(default_factory=list)
    working_directory: str | None = None

    # --- remote endpoint (streamable_http / sse) ---
    endpoint: str | None = None

    # --- auth ---
    auth_type: str = "none"
    auth_fields: list[AuthField] = field(default_factory=list)

    # --- legacy compat ---
    required_env_vars: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible dict matching Section 19 schema."""
        return {
            "source": {
                "type": self.source_type,
                "url": self.source_url,
                "repo": self.source_repo,
                "branch": self.source_branch,
                "subpath": self.source_subpath,
            },
            "transport": {
                "type": self.transport_type,
                "confidence": self.transport_confidence,
                "evidence": [e.to_dict() for e in self.transport_evidence],
            },
            "runtime": {
                "type": self.runtime_type,
            },
            "startup": {
                "command": self.command,
                "args": self.args,
                "working_directory": self.working_directory,
            },
            "endpoint": self.endpoint,
            "auth": {
                "type": self.auth_type,
                "schema": {
                    "fields": [f.to_dict() for f in self.auth_fields],
                },
            },
        }

    def to_analyze_repo_response(self) -> AnalyzeRepoResponse:
        """Convert to the legacy AnalyzeRepoResponse for backward compat."""
        # Build suggested_command: join command + args, or use working_directory prefix
        if self.command and self.args:
            suggested_command = " ".join([self.command] + self.args)
        elif self.command:
            suggested_command = self.command
        else:
            suggested_command = None

        return AnalyzeRepoResponse(
            detected=self.transport_type != "unknown",
            transport=self.transport_type,
            runtime=self.runtime_type,
            suggested_command=suggested_command,
            remote_endpoint=self.endpoint,
            required_env_vars=self.required_env_vars,
            auth_type=self.auth_type,
            hints=self.hints,
        )


# ---------------------------------------------------------------------------
# GitHub URL parser — Section 18: monorepo subpath handling
# ---------------------------------------------------------------------------

@dataclass
class ParsedGitHubURL:
    owner: str
    repo: str
    branch: str
    subpath: str | None


def _parse_github_url(url: str) -> ParsedGitHubURL:
    """Parse a GitHub URL into owner/repo/branch/subpath components.

    Handles:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      https://github.com/owner/repo/tree/main/src/filesystem
      https://github.com/owner/repo/tree/feature-branch/some/nested/path
    """
    # /tree/<branch>/<subpath>
    tree_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/tree/([^/]+)/(.+)$",
        url.rstrip("/"),
    )
    if tree_match:
        owner, repo, branch, subpath = tree_match.groups()
        return ParsedGitHubURL(owner=owner, repo=repo, branch=branch, subpath=subpath.strip("/"))

    # /tree/<branch>  (no subpath)
    branch_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/tree/([^/]+)/?$",
        url.rstrip("/"),
    )
    if branch_match:
        owner, repo, branch = branch_match.groups()
        return ParsedGitHubURL(owner=owner, repo=repo, branch=branch, subpath=None)

    # bare repo (no tree)
    base_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        url.rstrip("/"),
    )
    if base_match:
        owner, repo = base_match.groups()
        return ParsedGitHubURL(owner=owner, repo=repo, branch="main", subpath=None)

    return ParsedGitHubURL(owner="unknown", repo="unknown", branch="main", subpath=None)


# ---------------------------------------------------------------------------
# Transport evidence collector
# ---------------------------------------------------------------------------

# Source-code patterns → very strong confidence (0.95–1.00)
_SOURCE_CODE_TRANSPORT_PATTERNS: list[tuple[str, str, float]] = [
    # (regex_pattern, transport_type, confidence)
    (r"StdioServerTransport", "stdio", 0.98),
    (r"new\s+StdioServerParameters", "stdio", 0.97),
    (r"stdio_server\s*\(", "stdio", 0.97),
    (r"mcp\.run\(.*transport.*=.*stdio", "stdio", 0.96),
    (r"StreamableHTTPServerTransport", "streamable_http", 0.98),
    (r"StreamableHTTPTransport", "streamable_http", 0.97),
    (r"SSEServerTransport", "sse", 0.98),
    (r"new\s+SSEServer\b", "sse", 0.97),
]

# README keyword patterns → strong confidence (0.80–0.94)
_README_TRANSPORT_PATTERNS: list[tuple[str, str, float]] = [
    (r"\bstdio\b", "stdio", 0.85),
    (r"StdioServerTransport", "stdio", 0.90),
    (r"\bstreamable[\s_\-]?http\b", "streamable_http", 0.85),
    (r"\bsse\b|\bserver[\s_\-]?sent[\s_\-]?events?\b", "sse", 0.82),
    (r"\btransport.*=.*stdio", "stdio", 0.88),
]


def _collect_transport_evidence(scanned: dict[str, Any]) -> list[tuple[str, float, TransportEvidence]]:
    """Return list of (transport_type, confidence, evidence) tuples for all detected signals."""
    results: list[tuple[str, float, TransportEvidence]] = []

    def get(key: str) -> str:
        val = scanned.get(key, "")
        return val if isinstance(val, str) else str(val)

    # 1. Source code scan — very strong
    source_files = scanned.get("_source_files", {})  # dict[filename, content]
    if isinstance(source_files, dict):
        for fname, content in source_files.items():
            if not isinstance(content, str):
                continue
            for pattern, transport, conf in _SOURCE_CODE_TRANSPORT_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    results.append((
                        transport,
                        conf,
                        TransportEvidence(
                            source=f"source_code:{fname}",
                            reason=f"Pattern '{pattern}' found in {fname}",
                        ),
                    ))

    # 2. README — strong
    readme = get("README.md") or get("README.rst") or get("readme.md")
    if readme:
        for pattern, transport, conf in _README_TRANSPORT_PATTERNS:
            if re.search(pattern, readme, re.IGNORECASE):
                results.append((
                    transport,
                    conf,
                    TransportEvidence(
                        source="README",
                        reason=f"README mentions '{pattern}' transport pattern",
                    ),
                ))
        # Detect HTTP endpoint URLs in README (medium evidence for streamable_http)
        endpoint_urls = [
            u.rstrip(".,;:()\"'`")
            for u in re.findall(r"https?://[^\s'\"'`]+", readme)
            if re.search(r"/(?:mcp|sse|stream)$", u.rstrip(".,;:()\"'`"))
            and urlparse(u).hostname not in ("github.com", "www.github.com")
        ]
        if endpoint_urls:
            t = "sse" if re.search(r"/sse$", endpoint_urls[0]) else "streamable_http"
            results.append((
                t,
                0.50,
                TransportEvidence(
                    source="README",
                    reason=f"README contains HTTP endpoint URL: {endpoint_urls[0]}",
                ),
            ))

    # 3. package.json (node project → stdio strongly implied unless HTTP endpoint found)
    pkg_raw = get("package.json")
    if pkg_raw:
        results.append((
            "stdio",
            0.70,
            TransportEvidence(
                source="package.json",
                reason="Node.js project (package.json) — MCP servers default to stdio",
            ),
        ))
        # Look for HTTP server deps in deps section
        try:
            pkg = json.loads(pkg_raw)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "express" in deps or "fastify" in deps or "hono" in deps or "koa" in deps:
                results.append((
                    "streamable_http",
                    0.65,
                    TransportEvidence(
                        source="package.json",
                        reason="HTTP framework dependency found (express/fastify/hono) suggests HTTP transport",
                    ),
                ))
        except (json.JSONDecodeError, AttributeError):
            pass

    # 4. pyproject.toml / requirements.txt (python → stdio implied)
    if get("pyproject.toml") or get("requirements.txt"):
        results.append((
            "stdio",
            0.68,
            TransportEvidence(
                source="pyproject.toml" if get("pyproject.toml") else "requirements.txt",
                reason="Python project — MCP servers default to stdio",
            ),
        ))
        # Check for HTTP/ASGI deps
        combined = get("pyproject.toml") + get("requirements.txt")
        if re.search(r"\b(fastapi|flask|uvicorn|starlette|aiohttp|tornado)\b", combined, re.I):
            results.append((
                "streamable_http",
                0.65,
                TransportEvidence(
                    source="requirements",
                    reason="HTTP framework dependency (fastapi/flask/uvicorn) suggests HTTP transport",
                ),
            ))

    # 5. go.mod → stdio implied
    if get("go.mod"):
        results.append((
            "stdio",
            0.67,
            TransportEvidence(
                source="go.mod",
                reason="Go project (go.mod) — MCP servers default to stdio",
            ),
        ))

    # 6. Dockerfile / docker-compose → docker transport (weak)
    if get("Dockerfile") or get("dockerfile"):
        results.append((
            "docker",
            0.55,
            TransportEvidence(
                source="Dockerfile",
                reason="Dockerfile present — transport may be docker",
            ),
        ))
    if get("docker-compose.yml") or get("docker-compose.yaml"):
        results.append((
            "docker",
            0.45,
            TransportEvidence(
                source="docker-compose.yml",
                reason="docker-compose.yml present — transport may be docker",
            ),
        ))

    return results


def _best_transport(evidence_list: list[tuple[str, float, TransportEvidence]]) -> tuple[str, float, list[TransportEvidence]]:
    """Pick the highest-confidence transport type, collecting all supporting evidence."""
    if not evidence_list:
        return "unknown", 0.0, []

    # Find the transport with the maximum peak confidence
    by_transport: dict[str, list[tuple[float, TransportEvidence]]] = {}
    for transport, conf, ev in evidence_list:
        by_transport.setdefault(transport, []).append((conf, ev))

    best_transport = max(by_transport, key=lambda t: max(c for c, _ in by_transport[t]))
    best_entries = by_transport[best_transport]
    best_confidence = max(c for c, _ in best_entries)
    best_evidence = [ev for _, ev in best_entries]

    return best_transport, best_confidence, best_evidence


# ---------------------------------------------------------------------------
# Auth field builder (Section 11)
# ---------------------------------------------------------------------------

_LABEL_OVERRIDES: dict[str, str] = {
    "GITHUB_TOKEN": "GitHub Token",
    "GITHUB_PERSONAL_ACCESS_TOKEN": "GitHub Personal Access Token",
    "OPENAI_API_KEY": "OpenAI API Key",
    "ANTHROPIC_API_KEY": "Anthropic API Key",
    "SLACK_BOT_TOKEN": "Slack Bot Token",
    "SLACK_TEAM_ID": "Slack Team ID",
    "NOTION_API_TOKEN": "Notion API Token",
    "NOTION_TOKEN": "Notion Token",
    "STRIPE_SECRET_KEY": "Stripe Secret Key",
    "STRIPE_API_KEY": "Stripe API Key",
    "LINEAR_API_KEY": "Linear API Key",
    "JIRA_API_TOKEN": "Jira API Token",
    "JIRA_URL": "Jira Instance URL",
    "CONFLUENCE_URL": "Confluence URL",
    "GOOGLE_CLIENT_ID": "Google Client ID",
    "GOOGLE_CLIENT_SECRET": "Google Client Secret",
    "SUPABASE_URL": "Supabase Project URL",
    "SUPABASE_KEY": "Supabase API Key",
    "DATABASE_URL": "Database Connection URL",
    "BRAVE_API_KEY": "Brave Search API Key",
    "AWS_ACCESS_KEY_ID": "AWS Access Key ID",
    "AWS_SECRET_ACCESS_KEY": "AWS Secret Access Key",
    "AWS_REGION": "AWS Region",
    "AZURE_TENANT_ID": "Azure Tenant ID",
    "AZURE_CLIENT_ID": "Azure Client ID",
    "AZURE_CLIENT_SECRET": "Azure Client Secret",
}


def _var_name_to_label(name: str) -> str:
    """Convert SCREAMING_SNAKE env var name to a human-readable label."""
    if name in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[name]
    # "GITHUB_TOKEN" → "Github Token"
    return " ".join(word.capitalize() for word in name.split("_"))


def _var_field_type(name: str) -> str:
    """Classify field type based on naming conventions."""
    upper = name.upper()
    if any(upper.endswith(suffix) for suffix in ("_URL", "_URI", "_ENDPOINT", "_HOST")):
        return "url"
    return "secret"


def _build_auth_fields(env_vars: list[str]) -> list[AuthField]:
    """Convert a list of env var names to structured AuthField objects."""
    return [
        AuthField(
            name=v,
            label=_var_name_to_label(v),
            type=_var_field_type(v),
            required=True,
            location="env",
        )
        for v in env_vars
    ]


# ---------------------------------------------------------------------------
# Source code scanner helper
# ---------------------------------------------------------------------------

async def _scan_source_files(dir_path: Path) -> dict[str, str]:
    """Scan .ts, .js, .py, .go, .rs source files for transport patterns.

    Only reads the first 8 KB of each file, scans up to 20 files.
    Returns dict[filename, content].
    """
    source_files: dict[str, str] = {}
    extensions = {".ts", ".js", ".mjs", ".py", ".go", ".rs"}
    count = 0
    try:
        for fp in sorted(dir_path.rglob("*")):
            if count >= 20:
                break
            if fp.is_file() and fp.suffix in extensions and not any(
                part.startswith(".") or part in ("node_modules", "__pycache__", ".git", "dist", "build")
                for part in fp.parts
            ):
                try:
                    content = await asyncio.to_thread(fp.read_text, errors="ignore")
                    source_files[fp.name] = content[:8192]
                    count += 1
                except Exception:
                    pass
    except Exception:
        pass
    return source_files


# ---------------------------------------------------------------------------
# Registry of runtime manifest scanners (decoupled, pluggable)
# ---------------------------------------------------------------------------

_SCANNERS = {
    "github": lambda path, root: _scan_github_repo(path, root),
    "remote_http": lambda path, root: _scan_remote_http(path, root),
    "local_file": lambda path, root: _scan_local_file(path, root),
}


# ---------------------------------------------------------------------------
# Public API
def detect_source_type(source_url: str) -> str:
    """Detect whether source_url is a GitHub repository, remote HTTP endpoint, or local path."""
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("source_url must be a non-empty string")

    parsed = urlparse(source_url.strip())
    if parsed.scheme in ("http", "https"):
        host = (parsed.netloc or "").lower()
        if host == "github.com" or host.endswith(".github.com"):
            return "github"
        return "remote"

    return "local"


async def analyze_repo(repo_url: str) -> AnalyzeRepoResponse:
    """Universal analyzer — returns legacy AnalyzeRepoResponse for backward compat."""
    normalized = await analyze_repo_normalized(repo_url)
    return normalized.to_analyze_repo_response()


# In-memory cache of recent analyses, keyed by the (stripped) source URL.
# The UI flow always analyzes a URL twice — once for the "Analyze" preview
# (``analyze_repo`` above) and again inside ``mcp_service.add_mcp_server``
# when the user clicks "Add Server" — and each full analysis clones/fetches
# the repo over the network, so reusing a fresh result avoids doing that
# twice for the same URL. A short TTL keeps a fixed/updated repo from being
# stuck with a stale result for long.
_ANALYSIS_CACHE: dict[str, tuple[float, "NormalizedMCPConfig"]] = {}
_ANALYSIS_CACHE_TTL_SECONDS = 300


async def analyze_repo_normalized(repo_url: str) -> NormalizedMCPConfig:
    """Universal analyzer — returns a NormalizedMCPConfig with full evidence scoring.

    Caches its result per ``repo_url`` for ``_ANALYSIS_CACHE_TTL_SECONDS`` —
    see the cache's docstring above for why. Returns a deep copy on a cache
    hit so callers (e.g. ``add_mcp_server``, which mutates fields on the
    returned config) can't corrupt the cached entry for other callers.
    """
    logger.info(
        "analyzer_input",
        repo_url=repo_url,
        repo_url_type=type(repo_url).__name__,
    )

    if not repo_url or not isinstance(repo_url, str):
        raise ValueError(
            f"source_url must be a non-empty string, got {type(repo_url).__name__}"
        )

    repo_url = repo_url.strip()

    cached = _ANALYSIS_CACHE.get(repo_url)
    if cached is not None:
        cached_at, cached_config = cached
        if time.monotonic() - cached_at < _ANALYSIS_CACHE_TTL_SECONDS:
            logger.info("analyzer_cache_hit", repo_url=repo_url)
            return copy.deepcopy(cached_config)

    source_type = detect_source_type(repo_url)
    root = Path("/tmp/repo_analysis")

    if source_type == "github":
        result = await _analyze_github_repo_normalized(repo_url, root)
    elif source_type == "remote":
        result = await _analyze_remote_http_normalized(repo_url, root)
    else:
        result = await _analyze_local_path_normalized(repo_url, root)

    _ANALYSIS_CACHE[repo_url] = (time.monotonic(), copy.deepcopy(result))
    return result


# ---------------------------------------------------------------------------
# GitHub analysis
# ---------------------------------------------------------------------------

async def _analyze_github_repo_normalized(url: str, root: Path) -> NormalizedMCPConfig:
    """Clone or probe a GitHub repo and return NormalizedMCPConfig."""
    logger.info("analyzing_github_repo", repo_url=url)

    gh = _parse_github_url(url)
    scanned: dict[str, Any] = {}
    cloned_successfully = False
    clone_dir = None

    if gh.owner != "unknown":
        scanned = await _fetch_github_raw_manifests(gh.owner, gh.repo, branch=gh.branch, subpath=gh.subpath)

    has_manifests = any(
        k in scanned
        for k in ("package.json", "pyproject.toml", "requirements.txt",
                  "Dockerfile", "docker-compose.yml", "go.mod", "Cargo.toml", "README.md")
    )

    git_bin = shutil.which("git")
    if not has_manifests and git_bin:
        try:
            repo_slug = f"{gh.owner}_{gh.repo}".replace("/", "_")
            clone_dir = root / repo_slug

            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)

            canonical_url = f"https://github.com/{gh.owner}/{gh.repo}"
            subprocess.run(
                [git_bin, "clone", "--depth", "1", canonical_url, str(clone_dir)],
                check=True,
                capture_output=True,
                timeout=10,
            )

            # Navigate to subpath if applicable
            target_dir = clone_dir
            if gh.subpath:
                candidate = clone_dir / gh.subpath
                if candidate.is_dir():
                    target_dir = candidate

            scanned = await _scan_local_dir(target_dir)
            # Also scan source files for transport patterns
            scanned["_source_files"] = await _scan_source_files(target_dir)

            cloned_successfully = True
        except Exception as exc:
            logger.warning("git_clone_failed", repo_url=url, error=str(exc))

    # Check if we got anything useful
    has_manifests = any(
        k in scanned
        for k in ("package.json", "pyproject.toml", "requirements.txt",
                  "Dockerfile", "docker-compose.yml", "go.mod", "Cargo.toml", "README.md")
    )
    if not cloned_successfully and not has_manifests:
        if clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
        return NormalizedMCPConfig(
            source_type="github",
            source_url=url,
            source_repo=f"{gh.owner}/{gh.repo}",
            source_branch=gh.branch,
            source_subpath=gh.subpath,
            transport_type="unknown",
            transport_confidence=0.0,
            transport_evidence=[],
            runtime_type="unknown",
            hints=[f"GitHub repository not found or private: {url}"],
        )

    # If we cloned, clean up after building config (security: don't leave arbitrary code)
    try:
        config = _build_normalized_config(
            scanned=scanned,
            source_type="github",
            source_url=url,
            source_repo=f"{gh.owner}/{gh.repo}",
            source_branch=gh.branch,
            source_subpath=gh.subpath,
        )
    finally:
        if clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)

    return config


async def _analyze_remote_http_normalized(url: str, root: Path) -> NormalizedMCPConfig:
    """Probe a remote HTTP endpoint and return NormalizedMCPConfig.

    Uses the same detection algorithm as mcp_detect.detect_mcp_server (Section 14):
    1. Probe candidate endpoints (url, url/mcp, url/sse) with MCP initialize
    2. Classify based on response: 200 POST -> streamable_http, 200 GET+SSE -> sse
    3. 401/403 -> auth required, parse WWW-Authenticate, discover OAuth metadata
    4. Fallback to OAuth well-known discovery
    """
    logger.info("analyzing_remote_http", endpoint=url)
    try:
        # Reuse the detection logic from mcp_detect for consistency
        from vendor.services.mcp_detect import detect_mcp_server
        detection = await detect_mcp_server(url)

        transport = detection["transport"]
        endpoint = detection["endpoint"]
        auth_type = detection["auth_type"]
        transport_confidence = detection.get("transport_confidence", 0.5)
        transport_evidence = detection.get("transport_evidence", [])
        oauth = detection.get("oauth") or {}
        hints = detection.get("hints", [])

        # Build auth_fields from credential_fields in detection
        credential_fields = detection.get("credential_fields", [])
        auth_fields = []
        for cf in credential_fields:
            auth_fields.append(AuthField(
                name=cf["name"],
                label=cf["label"],
                type=cf.get("type", "secret"),
                required=cf.get("required", True),
                location=cf.get("location", "header"),
            ))

        # If no credential_fields but we have auth_type, build default fields
        if not auth_fields and auth_type not in ("none", "env", "unknown"):
            auth_fields = _build_auth_fields_for_auth_type(auth_type)

        return NormalizedMCPConfig(
            source_type="remote",
            source_url=url,
            transport_type=transport,
            transport_confidence=transport_confidence,
            transport_evidence=[TransportEvidence(**e) if isinstance(e, dict) else e for e in transport_evidence],
            runtime_type="remote",
            endpoint=endpoint,
            auth_type=auth_type,
            auth_fields=auth_fields,
            required_env_vars=[f.name for f in auth_fields if f.location == "env"],
            hints=hints,
        )
    except Exception as exc:
        logger.exception("remote_http_analysis_failed", endpoint=url)
        return NormalizedMCPConfig(
            source_type="remote",
            source_url=url,
            transport_type="unknown",
            transport_confidence=0.0,
            hints=[
                f"Failed to probe HTTP endpoint: {str(exc)}",
                "Ensure the endpoint is reachable and supports MCP protocol",
            ],
        )


def _build_auth_fields_for_auth_type(
    auth_type: str, is_github: bool = False, source_url: str = ""
) -> list[AuthField]:
    """Build default AuthField objects for a given auth_type."""
    if auth_type == "oauth2":
        return [
            AuthField(name="client_id", label="Client ID", type="text", required=True, location="env"),
            AuthField(name="client_secret", label="Client Secret", type="secret", required=True, location="env"),
        ]

    if auth_type in ("bearer", "env"):
        return [
            AuthField(
                name="access_token",
                label="Access Token / API Key",
                type="secret",
                required=True,
                location="header",
            )
        ]
    if auth_type == "api_key":
        return [
            AuthField(name="api_key", label="API Key", type="secret", required=True, location="header"),
        ]
    if auth_type == "basic":
        return [
            AuthField(name="username", label="Username", type="text", required=True, location="header"),
            AuthField(name="password", label="Password / API token", type="secret", required=True, location="header"),
        ]
    return []


async def _analyze_local_path_normalized(path: str, root: Path) -> NormalizedMCPConfig:
    """Analyze a local file system path and return NormalizedMCPConfig."""
    logger.info("analyzing_local_path", path=path)
    local_path = Path(path)
    if not local_path.exists():
        return NormalizedMCPConfig(
            source_type="local",
            source_url=path,
            transport_type="unknown",
            transport_confidence=0.0,
            hints=[f"Local path does not exist: {path}"],
        )

    if local_path.is_dir():
        scanned = await _scan_local_dir(local_path)
        scanned["_source_files"] = await _scan_source_files(local_path)
    else:
        scanned = await _scan_local_file(local_path)

    return _build_normalized_config(
        scanned=scanned,
        source_type="local",
        source_url=path,
    )


# ---------------------------------------------------------------------------
# Core builder — shared logic
# ---------------------------------------------------------------------------

def _build_normalized_config(
    scanned: dict[str, Any],
    source_type: str,
    source_url: str,
    source_repo: str = "",
    source_branch: str = "main",
    source_subpath: str | None = None,
) -> NormalizedMCPConfig:
    """Build NormalizedMCPConfig from a dict of scanned manifests."""
    # Collect evidence for transport
    evidence_list = _collect_transport_evidence(scanned)
    transport_type, transport_confidence, transport_evidence = _best_transport(evidence_list)

    # Infer runtime and command (reuse existing heuristic)
    legacy_transport, runtime_type, raw_command, remote_endpoint = _infer_transport_and_runtime(scanned)

    # If evidence collection found a clear winner, prefer it over the legacy heuristic
    if transport_confidence >= 0.60 and transport_type != "unknown":
        final_transport = transport_type
    else:
        final_transport = legacy_transport
        if not transport_evidence and final_transport != "unknown":
            transport_evidence = [TransportEvidence(
                source="heuristic",
                reason=f"Inferred from manifest structure as {final_transport}",
            )]

    # Determine working_directory from subpath (Section 18)
    working_directory: str | None = None
    if source_subpath:
        working_directory = source_subpath

    # Build command + args
    command: str | None = None
    args: list[str] = []
    if raw_command:
        parts = raw_command.split()
        if parts:
            # Strip leading subpath prefix that the legacy code prepends
            if source_subpath and parts[0].startswith(source_subpath + "/"):
                parts[0] = parts[0][len(source_subpath) + 1:]
            command = parts[0]
            args = parts[1:]

    # Auth
    auth_type = _detect_auth_type(scanned, remote_endpoint)
    env_vars = _extract_env_vars(scanned)
    if auth_type == "oauth2" or any(v.endswith("_OAUTH_CREDENTIALS") or v.endswith("_CREDENTIALS_JSON") for v in env_vars):
        auth_type = "oauth2"

    # Build fields from whatever real env vars this repo actually declares
    # (its own names, e.g. QUICKBOOKS_CLIENT_ID/QUICKBOOKS_REFRESH_TOKEN) —
    # a local stdio server manages its own OAuth/token lifecycle internally
    # and just wants these as plain config, so nothing here is renamed to a
    # generic placeholder or dropped just because auth_type == "oauth2".
    # The generic client_id/client_secret (or api_key, username/password, …)
    # fallback below only kicks in when we found no concrete field at all —
    # e.g. a repo that says "OAuth" without documenting its actual env vars.
    auth_fields = _build_auth_fields(env_vars)
    if not auth_fields and auth_type not in ("none", "unknown"):
        auth_fields = _build_auth_fields_for_auth_type(
            auth_type, is_github=(source_type == "github"), source_url=source_url
        )
        for f in auth_fields:
            if f.location == "env" and f.name not in env_vars:
                env_vars.append(f.name)

    return NormalizedMCPConfig(
        source_type=source_type,
        source_url=source_url,
        source_repo=source_repo,
        source_branch=source_branch,
        source_subpath=source_subpath,
        transport_type=final_transport,
        transport_confidence=transport_confidence,
        transport_evidence=transport_evidence,
        runtime_type=runtime_type,
        command=command,
        args=args,
        working_directory=working_directory,
        endpoint=remote_endpoint,
        auth_type=auth_type,
        auth_fields=auth_fields,
        required_env_vars=env_vars,
        hints=[],
    )


# ---------------------------------------------------------------------------
# Backward-compat wrappers used by legacy callers
# ---------------------------------------------------------------------------

async def _analyze_github_repo(url: str, parsed, root: Path) -> AnalyzeRepoResponse:
    return (await _analyze_github_repo_normalized(url, root)).to_analyze_repo_response()


async def _analyze_remote_http(url: str, parsed, root: Path) -> AnalyzeRepoResponse:
    return (await _analyze_remote_http_normalized(url, root)).to_analyze_repo_response()


async def _analyze_local_path(path: str, parsed, root: Path) -> AnalyzeRepoResponse:
    return (await _analyze_local_path_normalized(path, root)).to_analyze_repo_response()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _best_python_entry(
    pyproject_content: str,
    requirements_content: str,
    python_files: list[str] | None,
) -> str:
    """Pick the most likely Python entry file."""
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


async def _verify_npm_package(package_name: str) -> bool:
    """Verify that an npm package exists in the registry (Rule 11)."""
    try:
        async with AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://registry.npmjs.org/{package_name}")
            return resp.status_code == 200
    except Exception:
        return False


def _extract_default_cli_args(scanned: dict[str, Any]) -> str:
    """Extract default CLI positional arguments generically by inspecting README.md evidence.

    If the README indicates required path/directory parameters (e.g. `<path>`,
    `<dir>`, `<directory>`, `<allowed-directory>`, `<folder>`), defaults to `.`
    (current working directory).
    """
    readme = scanned.get("README.md", "")
    if isinstance(readme, str) and readme:
        if re.search(r"<(?:path|dir|directory|allowed-directory|folder|root)>", readme, re.IGNORECASE):
            return " ."
    return ""


def _infer_transport_and_runtime(
    scanned: dict[str, Any],
) -> tuple[str, str, str | None, str | None]:
    """Convert scanned manifests into transport/runtime/command/remote_endpoint.

    Deterministic heuristic — preserves original logic from before the refactor.
    """
    transport = "stdio"
    runtime = "custom"
    command = None
    remote_endpoint = None

    def get_content(key: str) -> str:
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            return str(val)
        return ""

    # Manifest-first preference (Node, Python, Go, Rust, Docker)
    if get_content("package.json"):
        transport = "stdio"
        runtime = "node"
        pkg_content = get_content("package.json")
        try:
            pkg = json.loads(pkg_content) if isinstance(pkg_content, str) else pkg_content
            pkg_name = pkg.get("name")
            pkg_bin = pkg.get("bin")
            bin_entry = None
            if isinstance(pkg_bin, dict):
                bin_entry = next(iter(pkg_bin.values()), None)
            elif isinstance(pkg_bin, str):
                bin_entry = pkg_bin

            # Rule 11: Verify npm package exists before using npx
            is_published_npm = pkg_name and (
                pkg_name.startswith("@modelcontextprotocol/")
                or pkg_name.startswith("@playwright/")
                or pkg_name.startswith("@xeroapi/")
                or pkg_name in (
                    "@notionhq/notion-mcp-server",
                    "pipedrive-mcp-server",
                    "brave-search-mcp-server",
                )
            )

            # For GitHub repos, prefer local build over npx unless verified published
            if is_published_npm and pkg_bin:
                # Note: actual verification happens at runtime in mcp_client._prepare_local_repo_stdio
                extra_arg = _extract_default_cli_args(scanned)
                command = f"npx -y {pkg_name}{extra_arg}"
            elif bin_entry:
                command = f"node {bin_entry}"
            elif pkg_name:
                main = pkg.get("main") or "dist/index.js"
                command = f"node {main}"
            else:
                script = pkg.get("scripts", {}).get("start") or pkg.get("scripts", {}).get("dev")
                command = "npm start" if script else "node index.js"
        except (json.JSONDecodeError, AttributeError):
            command = "npm start"

    elif get_content("pyproject.toml") or get_content("requirements.txt"):
        transport = "stdio"
        runtime = "python"
        pyproject_content = get_content("pyproject.toml")
        entry = _best_python_entry(
            pyproject_content, get_content("requirements.txt"), scanned.get("python_files")
        )
        subdir = scanned.get("_server_subdir")
        if subdir:
            command = f"python {subdir}/{entry}"
        else:
            command = f"python {entry}"

    elif get_content("go.mod"):
        transport = "stdio"
        runtime = "go"
        cmd_entries = [k for k in scanned if k.startswith("cmd/") and k.endswith("main.go")]
        readme = get_content("README.md").lower()
        source_files_content = (
            " ".join(scanned.get("_source_files", {}).values()).lower()
            if isinstance(scanned.get("_source_files"), dict)
            else ""
        )
        sub_arg = (
            " stdio"
            if (
                "stdio" in readme
                or "stdio" in source_files_content
                or "cobra" in source_files_content
                or "github-mcp-server" in readme
            )
            else ""
        )
        if cmd_entries:
            sub = cmd_entries[0].split("/")[1]
            command = f"go run ./cmd/{sub}{sub_arg}"
        else:
            command = f"go run .{sub_arg}"

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

    elif get_content("README.md"):
        readme = get_content("README.md")
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
        if any(kw in readme.lower() for kw in ["docker", "container", "compose"]):
            runtime = "docker"
            transport = "docker"

    manifest_content = get_content("manifest")
    if not remote_endpoint and "://" in manifest_content:
        candidate = manifest_content.strip()
        if urlparse(candidate).hostname not in ("github.com", "www.github.com"):
            remote_endpoint = candidate
            transport = "streamable_http"
            runtime = "remote"

    return transport, runtime, command, remote_endpoint


async def _fetch_github_raw_manifests(
    owner: str,
    repo: str,
    branch: str = "main",
    subpath: str | None = None,
) -> dict[str, Any]:
    """Fetch repository manifest files over HTTPS raw API when git is not available.

    If a subpath is given, tries the subpath first, then falls back to the repo root.
    """
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
        "main.py",
        "server.py",
        "app.py",
        "mcp_server.py",
        "index.js",
        "index.ts",
    ]
    candidate_subpaths: list[str] = []
    if subpath:
        candidate_subpaths.append(subpath)
    candidate_subpaths.extend([
        f"{repo}-mcp-server",
        f"{repo}-server",
        f"{repo}-mcp",
        "mcp-server",
        "server",
    ])

    scanned: dict[str, Any] = {}
    async with AsyncClient(follow_redirects=True, timeout=10.0) as client:
        for fname in files_to_check:
            branches_to_try = [branch] if branch != "main" else ["main", "master", "HEAD"]
            for b in branches_to_try:
                paths_to_try: list[str] = [fname]
                for sub in candidate_subpaths:
                    paths_to_try.append(f"{sub}/{fname}")

                for fpath in paths_to_try:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{b}/{fpath}"
                    try:
                        res = await client.get(raw_url)
                        if res.status_code == 200:
                            scanned[fname] = res.text
                            if fname.endswith(".py"):
                                scanned.setdefault("python_files", []).append(fname)
                            if "/" in fpath:
                                scanned["_server_subdir"] = fpath.rsplit("/", 1)[0]
                            break
                    except Exception:
                        pass
                if fname in scanned:
                    break

    if subpath and "_server_subdir" not in scanned:
        scanned["_server_subdir"] = subpath
    return scanned


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

_CREDENTIAL_SUFFIXES = (
    "TOKEN|KEY|SECRET|PASSWORD|AUTH|API|ID|URL|URI|PAT|CLIENT_ID|ACCESS_KEY|"
    "CREDENTIALS|USERNAME|CONNECTION_STRING|PERSONAL_ACCESS_TOKEN|DB|ENDPOINT|"
    "CONSUMER_KEY|CONSUMER_SECRET|INSTANCE|REALM_ID"
)

_CREDENTIAL_ENV_KEY_RE = re.compile(
    r"\b([A-Z0-9_]{2,}_(?:" + _CREDENTIAL_SUFFIXES + r"))\b",
    re.IGNORECASE,
)
_CREDENTIAL_ENV_DECL_RE = re.compile(
    r"(?:export\s+)?([A-Za-z0-9_]{2,}_(?:" + _CREDENTIAL_SUFFIXES + r"))=",
    re.IGNORECASE,
)


def _extract_env_vars(scanned: dict[str, Any]) -> list[str]:
    """Extract required environment variables from scanned manifests.

    Returns every detected name as-is (e.g. ``QUICKBOOKS_REFRESH_TOKEN``,
    ``QUICKBOOKS_REALM_ID``) — a local stdio MCP server frequently expects a
    pre-obtained refresh token or other repo-specific identifier as plain
    static config (it manages its own token lifecycle internally, with no
    interactive OAuth step our platform is involved in), so token-shaped
    names are not treated as special or excluded here.
    """
    env_vars: set[str] = set()

    def get_content(key: str) -> str:
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            return str(val)
        return ""

    for env_file in [
        "env", "env.example", ".env", ".env.example",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "server.json", "smithery.yaml",
    ]:
        content = get_content(env_file)
        if content:
            for m in _CREDENTIAL_ENV_KEY_RE.findall(content):
                m_upper = m.upper()
                if m_upper not in IGNORED_SYSTEM_ENV_VARS:
                    env_vars.add(m_upper)

    for key in ["manifest", "README.md"]:
        content = get_content(key)
        if content:
            for m in _CREDENTIAL_ENV_DECL_RE.findall(content):
                m_upper = m.upper()
                if m_upper not in IGNORED_SYSTEM_ENV_VARS:
                    env_vars.add(m_upper)

    cleaned = []
    for v in env_vars:
        if v in IGNORED_SYSTEM_ENV_VARS:
            continue
        # _EXPIRES_IN is response metadata (a computed TTL), never something
        # a human supplies — the only var name shape still worth excluding.
        if v.endswith("_EXPIRES_IN"):
            continue
        cleaned.append(v)

    return sorted(cleaned)


def _detect_auth_type(scanned: dict[str, Any], remote_endpoint: str | None = None) -> str:
    """Detect authentication type.  Returns: none | api_key | bearer | basic | oauth2 | env."""
    def get_content(key: str) -> str:
        val = scanned.get(key, "")
        if isinstance(val, str):
            return val
        elif isinstance(val, dict):
            return str(val)
        return ""

    hints = []
    env_vars = _extract_env_vars(scanned)
    if env_vars:
        hints.append("env_detected")

    # Check manifest (formal manifest) first
    manifest_content = get_content("manifest")
    if manifest_content:
        mc = manifest_content.lower()
        if "bearer" in mc:
            hints.append("bearer_detected")
        if "api_key" in mc or "api-key" in mc or "x-api-key" in mc:
            hints.append("api_key_detected")
        if "oauth" in mc:
            hints.append("oauth_detected")
        if "basic" in mc:
            hints.append("basic_detected")

    # Check README.md for explicit auth declarations
    readme_content = get_content("README.md")
    if readme_content:
        rc = readme_content.lower()
        if "authorization: bearer" in rc or "bearer token" in rc:
            hints.append("bearer_detected")
        if "x-api-key" in rc or "api_key:" in rc or "api-key:" in rc or "x-api-key:" in rc:
            hints.append("api_key_detected")
        if "oauth" in rc or "client_id" in rc or "google consent" in rc or "credentials.json" in rc:
            hints.append("oauth_detected")
        if any(kw in rc for kw in ("qr code", "scan qr", "scan the qr", "pairing code", "link a device", "linked devices")):
            hints.append("device_pairing_detected")

    if any("bearer" in h for h in hints):
        return "bearer"
    if any("api_key" in h for h in hints):
        return "api_key"
    if any("oauth" in h for h in hints):
        return "oauth2"
    if any("basic" in h for h in hints):
        return "basic"
    if any("device_pairing" in h for h in hints):
        return "device_pairing"
    if any("env" in h for h in hints):
        return "env"

    return "none"


async def _read_file_safely(file_path: Path) -> str:
    """Safely read file contents with error handling."""
    try:
        if file_path.exists():
            content = await asyncio.to_thread(file_path.read_text, errors="ignore")
            return content[:10000]
        return ""
    except Exception as exc:
        logger.debug("Failed to read file", path=str(file_path), error=str(exc))
        return ""


async def _scan_local_dir(dir_path: Path) -> dict[str, Any]:
    """Scan a local directory for MCP server manifests.

    Scans the top level first, then drills into the immediate subdirectory
    that carries the most manifest files if no build manifests are found.
    """
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
    scanned: dict[str, Any] = {}
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
    """Legacy: Recursively scan GitHub repository tree for MCP server manifests."""
    scanned: dict[str, Any] = {}

    def process_item(item):
        if item.type == "file":
            name = item.name
            if name in [
                "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                "package.json", "pyproject.toml", "requirements.txt",
                "setup.py", "setup.cfg", "go.mod", "Cargo.toml",
                "README.md", ".env.example", ".env",
            ]:
                if not scanned.get(name):
                    scanned[name] = item.download_url
            elif name.endswith(".py"):
                if "python_files" not in scanned:
                    scanned["python_files"] = []
                scanned["python_files"].append(name)
        elif item.type == "dir":
            for subitem in item.contents:
                process_item(subitem)

    for item in items:
        process_item(item)

    return scanned


async def _scan_github_repo(url: str, root: Path) -> dict[str, Any]:
    """Legacy method — use _analyze_github_repo_normalized directly."""
    logger.warning("Using deprecated _scan_github_repo method")
    return {}


async def _scan_remote_http(url: str, root: Path) -> dict[str, Any]:
    """Legacy method — use _analyze_remote_http_normalized directly."""
    logger.warning("Using deprecated _scan_remote_http method")
    return {}


__all__ = [
    "analyze_repo",
    "analyze_repo_normalized",
    "detect_source_type",
    "NormalizedMCPConfig",
    "TransportEvidence",
    "AuthField",
]
