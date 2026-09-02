"""Unit tests for the Universal MCP Repository Analyzer.

Tests the dynamic detection of transport, runtime, commands, and environment
variables from various repository types (GitHub, local paths, remote HTTP).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from vendor_resources.services.repo_analyzer import (
    analyze_repo,
    _infer_transport_and_runtime,
    _extract_env_vars,
    _detect_auth_type,
)


class TestInferTransportAndRuntime:
    """Tests for transport/runtime inference from scanned manifests."""

    def test_dockerfile_detected(self):
        """Dockerfile should indicate docker transport and runtime."""
        scanned = {
            "Dockerfile": "FROM python:3.11\nWORKDIR /app\nCOPY . .\nCMD python server.py",
        }
        transport, runtime, command, remote = _infer_transport_and_runtime(scanned)
        assert transport == "docker"
        assert runtime == "docker"
        assert "docker" in command

    def test_package_json_node_detected(self):
        """package.json should indicate Node.js stdio transport."""
        scanned = {
            "package.json": '{"name": "mcp-server", "scripts": {"start": "node server.js"}}',
        }
        transport, runtime, command, remote = _infer_transport_and_runtime(scanned)
        assert transport == "stdio"
        assert runtime == "node"
        assert "npx" in command or "node" in command

    def test_pyproject_toml_python_detected(self):
        """pyproject.toml should indicate Python stdio transport."""
        scanned = {
            "pyproject.toml": '[tool.mcp]\nserver = "server.py"',
        }
        transport, runtime, command, remote = _infer_transport_and_runtime(scanned)
        assert transport == "stdio"
        assert runtime == "python"
        assert "python" in command

    def test_go_mod_go_detected(self):
        """go.mod should indicate Go stdio transport."""
        scanned = {
            "go.mod": "module github.com/org/mcp-server\n",
        }
        transport, runtime, command, remote = _infer_transport_and_runtime(scanned)
        assert transport == "stdio"
        assert runtime == "go"
        assert "go run" in command

    def test_cargo_toml_rust_detected(self):
        """Cargo.toml should indicate Rust stdio transport."""
        scanned = {
            "Cargo.toml": '[package]\nname = "mcp-server"\n',
        }
        transport, runtime, command, remote = _infer_transport_and_runtime(scanned)
        assert transport == "stdio"
        assert runtime == "rust"
        assert "cargo run" in command

    def test_package_json_with_bin_uses_npx(self):
        """A package with a published CLI (bin) should run via npx."""
        scanned = {
            "package.json": '{"name": "@notionhq/notion-mcp-server", "bin": {"notion-mcp-server": "dist/index.js"}, "main": "index.js"}',
        }
        transport, runtime, command, _remote = _infer_transport_and_runtime(scanned)
        assert transport == "stdio"
        assert runtime == "node"
        assert command == "npx -y @notionhq/notion-mcp-server"

    def test_package_json_name_without_bin_runs_from_source(self):
        """A package with a name but no bin is NOT runnable via npx — run from source."""
        scanned = {
            "package.json": '{"name": "@qboapi/qbo-mcp-server", "main": "dist/index.js"}',
        }
        transport, runtime, command, _remote = _infer_transport_and_runtime(scanned)
        assert transport == "stdio"
        assert runtime == "node"
        assert command == "node dist/index.js"

    def test_readme_ignores_github_repo_url(self):
        """A GitHub repo URL in a README must never be treated as a remote endpoint."""
        scanned = {
            "README.md": "Run it: https://github.com/lharries/whatsapp-mcp/sse",
        }
        transport, runtime, _command, remote = _infer_transport_and_runtime(scanned)
        assert remote is None
        assert transport == "stdio"

    def test_readme_picks_non_github_endpoint(self):
        """A real remote endpoint is still detected even when a GitHub URL is present."""
        scanned = {
            "README.md": (
                "Repo: https://github.com/org/some-srv/mcp\n"
                "Endpoint: https://api.example.com/mcp"
            ),
        }
        _transport, _runtime, _command, remote = _infer_transport_and_runtime(scanned)
        assert remote == "https://api.example.com/mcp"

    def test_docker_compose_detected(self):
        """docker-compose.yml should indicate docker transport."""
        scanned = {
            "docker-compose.yml": "services:\n  mcp:\n    image: mcp/server",
        }
        transport, runtime, command, remote = _infer_transport_and_runtime(scanned)
        assert transport == "docker"
        assert runtime == "docker"
        assert "docker-compose" in command


class TestExtractEnvVars:
    """Tests for environment variable extraction from manifests."""

    def test_env_example_extraction(self):
        """Should extract standard env vars from .env.example."""
        scanned = {
            ".env.example": "GITHUB_TOKEN=xxx\nOPENAI_API_KEY=yyy\nDATABASE_URL=postgresql://...",
        }
        vars = _extract_env_vars(scanned)
        assert "GITHUB_TOKEN" in vars
        assert "OPENAI_API_KEY" in vars
        assert "DATABASE_URL" in vars

    def test_pat_declaration_detected(self):
        """Any ``*_pat=`` declaration should be extracted (no GitHub special case)."""
        scanned = {
            "manifest": "github_pat=abc123\ngitlab_pat=def456",
        }
        vars = _extract_env_vars(scanned)
        assert "GITHUB_PAT" in vars
        assert "GITLAB_PAT" in vars

    def test_token_declaration_in_readme_detected(self):
        """``export FOO_TOKEN=`` in a README should be extracted generically."""
        scanned = {
            "README.md": "export MY_SERVICE_TOKEN=secret\nexport MY_SERVICE_KEY=other",
        }
        vars = _extract_env_vars(scanned)
        assert "MY_SERVICE_TOKEN" in vars
        assert "MY_SERVICE_KEY" in vars

    def test_system_env_vars_filtered(self):
        """Should filter out system/runtime variables like NODE_PATH and PYTHONPATH."""
        scanned = {
            ".env.example": "NODE_PATH=/usr/lib\nPYTHONPATH=/app\nMY_SERVICE_API_KEY=secret123\n",
        }
        vars = _extract_env_vars(scanned)
        assert "MY_SERVICE_API_KEY" in vars
        assert "NODE_PATH" not in vars
        assert "PYTHONPATH" not in vars


class TestDetectAuthType:
    """Tests for authentication type detection."""

    def test_bearer_token_detected(self):
        """Bearer token in manifest should indicate bearer auth."""
        scanned = {"manifest": "Authorization: Bearer xxx"}
        auth = _detect_auth_type(scanned, None)
        assert auth == "bearer"

    def test_api_key_detected(self):
        """API key in manifest should indicate api_key auth."""
        scanned = {"manifest": "x-api-key: secret"}
        auth = _detect_auth_type(scanned, None)
        assert auth == "api_key"

    def test_oauth_detected(self):
        """OAuth in manifest should indicate oauth2 auth."""
        scanned = {"manifest": "oauth2 flow required"}
        auth = _detect_auth_type(scanned, None)
        assert auth == "oauth2"

    def test_basic_auth_detected(self):
        """Basic auth in manifest should indicate basic auth."""
        scanned = {"manifest": "basic auth required"}
        auth = _detect_auth_type(scanned, None)
        assert auth == "basic"

    def test_hostname_never_guesses_auth(self):
        """Hostname must never decide auth — github.com/openai.com URLs are ignored."""
        scanned = {}
        assert _detect_auth_type(scanned, "https://github.com/api") == "none"
        assert _detect_auth_type(scanned, "https://api.openai.com/v1") == "none"
        assert _detect_auth_type(scanned, "https://slack.com/api") == "none"

    def test_documented_auth_wins_over_url(self):
        """What the server documents is used, even when the URL is a known host."""
        scanned = {"README.md": "Set MY_KEY as an x-api-key header: x-api-key <MY_KEY>"}
        auth = _detect_auth_type(scanned, "https://api.openai.com/v1")
        assert auth == "api_key"

    def test_env_vars_only_returns_env(self):
        """A credential-style env var with no stronger hint should classify as env."""
        scanned = {".env.example": "NOTION_TOKEN=ntn_xxx"}
        auth = _detect_auth_type(scanned, None)
        assert auth == "env"

    def test_unknown_defaults_to_none(self):
        """Unknown endpoints should default to none auth."""
        scanned = {}
        auth = _detect_auth_type(scanned, "https://unknown.example.com")
        assert auth == "none"


class TestAnalyzeRepo:
    """Integration tests for the analyze_repo function."""

    @pytest.mark.asyncio
    async def test_analyze_github_repo_returns_valid_response(self):
        """Analyze GitHub repo should return valid AnalyzeRepoResponse."""
        # We mock the analyze_repo internals since it does network/git operations
        with patch("vendor_resources.services.repo_analyzer._analyze_github_repo") as mock_analyze:
            mock_analyze.return_value = MagicMock(
                detected=True,
                transport="stdio",
                runtime="node",
                suggested_command="npx -y mcp-server",
                remote_endpoint=None,
                required_env_vars=["GITHUB_TOKEN"],
                auth_type="bearer",
                hints=["GitHub repo analyzed"],
            )
            
            result = await analyze_repo("https://github.com/org/mcp-server")
            
            assert result.detected is True
            assert result.transport == "stdio"
            assert result.runtime == "node"
            assert result.suggested_command == "npx -y mcp-server"
            assert "GITHUB_TOKEN" in result.required_env_vars
            assert result.auth_type == "bearer"

    @pytest.mark.asyncio
    async def test_analyze_remote_http_returns_valid_response(self):
        """Analyze remote HTTP endpoint should return valid response."""
        with patch("vendor_resources.services.repo_analyzer._analyze_remote_http") as mock_analyze:
            mock_analyze.return_value = MagicMock(
                detected=True,
                transport="streamable_http",
                runtime="remote",
                suggested_command=None,
                remote_endpoint="https://api.example.com/mcp",
                required_env_vars=["API_KEY"],
                auth_type="api_key",
                hints=["Remote HTTP endpoint probed"],
            )
            
            result = await analyze_repo("https://api.example.com/mcp")
            
            assert result.detected is True
            assert result.transport == "streamable_http"
            assert result.runtime == "remote"
            assert result.remote_endpoint == "https://api.example.com/mcp"
            assert result.auth_type == "api_key"

    @pytest.mark.asyncio
    async def test_analyze_local_path_returns_valid_response(self):
        """Analyze local path should return valid response."""
        with patch("vendor_resources.services.repo_analyzer._analyze_local_path") as mock_analyze:
            mock_analyze.return_value = MagicMock(
                detected=True,
                transport="stdio",
                runtime="python",
                suggested_command="python server.py",
                remote_endpoint=None,
                required_env_vars=["OPENAI_API_KEY"],
                auth_type="api_key",
                hints=["Local directory analyzed"],
            )
            
            result = await analyze_repo("/local/path/to/mcp")
            
            assert result.detected is True
            assert result.transport == "stdio"
            assert result.runtime == "python"
            assert result.suggested_command == "python server.py"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])