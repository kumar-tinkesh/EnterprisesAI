"""Data models and URL parsing for repo_analyzer."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from vendor.api.v1.schemas import AnalyzeRepoResponse


@dataclass
class TransportEvidence:
    """A single piece of evidence supporting a transport classification."""
    source: str   # e.g. "README", "source_code", "package.json"
    reason: str   # human-readable explanation

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "reason": self.reason}


@dataclass
class AuthField:
    """Describes one field the UI should render when collecting credentials."""
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
    """Fully normalized MCP server configuration."""
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


@dataclass
class ParsedGitHubURL:
    owner: str
    repo: str
    branch: str
    subpath: str | None


def _parse_github_url(url: str) -> ParsedGitHubURL:
    """Parse a GitHub URL into owner/repo/branch/subpath components."""
    tree_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/tree/([^/]+)/(.+)$",
        url.rstrip("/"),
    )
    if tree_match:
        owner, repo, branch, subpath = tree_match.groups()
        return ParsedGitHubURL(owner=owner, repo=repo, branch=branch, subpath=subpath.strip("/"))

    branch_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/tree/([^/]+)/?$",
        url.rstrip("/"),
    )
    if branch_match:
        owner, repo, branch = branch_match.groups()
        return ParsedGitHubURL(owner=owner, repo=repo, branch=branch, subpath=None)

    base_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        url.rstrip("/"),
    )
    if base_match:
        owner, repo = base_match.groups()
        return ParsedGitHubURL(owner=owner, repo=repo, branch="main", subpath=None)

    return ParsedGitHubURL(owner="unknown", repo="unknown", branch="main", subpath=None)
