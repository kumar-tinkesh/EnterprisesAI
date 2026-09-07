"""Transport evidence collection, runtime inference, and auth field generation."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from httpx import AsyncClient

from vendor.services.repo_analyzer.types import AuthField, TransportEvidence

# Source-code patterns → very strong confidence (0.95–1.00)
_SOURCE_CODE_TRANSPORT_PATTERNS: list[tuple[str, str, float]] = [
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

    source_files = scanned.get("_source_files", {})
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

    if get("pyproject.toml") or get("requirements.txt"):
        results.append((
            "stdio",
            0.68,
            TransportEvidence(
                source="pyproject.toml" if get("pyproject.toml") else "requirements.txt",
                reason="Python project — MCP servers default to stdio",
            ),
        ))
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

    if get("go.mod"):
        results.append((
            "stdio",
            0.67,
            TransportEvidence(
                source="go.mod",
                reason="Go project (go.mod) — MCP servers default to stdio",
            ),
        ))

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

    by_transport: dict[str, list[tuple[float, TransportEvidence]]] = {}
    for transport, conf, ev in evidence_list:
        by_transport.setdefault(transport, []).append((conf, ev))

    best_transport = max(by_transport, key=lambda t: max(c for c, _ in by_transport[t]))
    best_entries = by_transport[best_transport]
    best_confidence = max(c for c, _ in best_entries)
    best_evidence = [ev for _, ev in best_entries]

    return best_transport, best_confidence, best_evidence


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
    """Verify that an npm package exists in the registry."""
    try:
        async with AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://registry.npmjs.org/{package_name}")
            return resp.status_code == 200
    except Exception:
        return False


def _extract_default_cli_args(scanned: dict[str, Any]) -> str:
    """Extract default CLI positional arguments generically by inspecting README.md evidence."""
    readme = scanned.get("README.md", "")
    if isinstance(readme, str) and readme:
        if re.search(r"<(?:path|dir|directory|allowed-directory|folder|root)>", readme, re.IGNORECASE):
            return " ."
    return ""


def _infer_transport_and_runtime(
    scanned: dict[str, Any],
) -> tuple[str, str, str | None, str | None]:
    """Convert scanned manifests into transport/runtime/command/remote_endpoint."""
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

            if is_published_npm and pkg_bin:
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
    """Extract required environment variables from scanned manifests."""
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
        if v.endswith("_EXPIRES_IN"):
            continue
        cleaned.append(v)

    return sorted(cleaned)


def _detect_auth_type(scanned: dict[str, Any], remote_endpoint: str | None = None) -> str:
    """Detect authentication type."""
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
