"""Main repository analyzer entry points and normalized config builders."""
from __future__ import annotations

import copy
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog

from vendor.api.v1.schemas import AnalyzeRepoResponse
from vendor.services.repo_analyzer.inference import (
    _best_transport,
    _build_auth_fields,
    _collect_transport_evidence,
    _detect_auth_type,
    _extract_env_vars,
    _infer_transport_and_runtime,
)
from vendor.services.repo_analyzer.scanners import (
    _fetch_github_raw_manifests,
    _scan_local_dir,
    _scan_local_file,
    _scan_source_files,
)
from vendor.services.repo_analyzer.types import (
    AuthField,
    NormalizedMCPConfig,
    TransportEvidence,
    _parse_github_url,
)

logger = structlog.get_logger(__name__)

_ANALYSIS_CACHE: dict[str, tuple[float, NormalizedMCPConfig]] = {}
_ANALYSIS_CACHE_TTL_SECONDS = 300


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
    from vendor.services import repo_analyzer
    norm_fn = getattr(repo_analyzer, "analyze_repo_normalized", analyze_repo_normalized)
    normalized = await norm_fn(repo_url)
    return normalized.to_analyze_repo_response()


async def analyze_repo_normalized(repo_url: str) -> NormalizedMCPConfig:
    """Universal analyzer — returns a NormalizedMCPConfig with full evidence scoring."""
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

    from vendor.services import repo_analyzer
    detect_source_fn = getattr(repo_analyzer, "detect_source_type", detect_source_type)
    source_type = detect_source_fn(repo_url)
    root = Path("/tmp/repo_analysis")

    if source_type == "github":
        gh_fn = getattr(repo_analyzer, "_analyze_github_repo_normalized", _analyze_github_repo_normalized)
        result = await gh_fn(repo_url, root)
    elif source_type == "remote":
        remote_fn = getattr(repo_analyzer, "_analyze_remote_http_normalized", _analyze_remote_http_normalized)
        result = await remote_fn(repo_url, root)
    else:
        local_fn = getattr(repo_analyzer, "_analyze_local_path_normalized", _analyze_local_path_normalized)
        result = await local_fn(repo_url, root)

    _ANALYSIS_CACHE[repo_url] = (time.monotonic(), copy.deepcopy(result))
    return result


async def _analyze_github_repo_normalized(url: str, root: Path) -> NormalizedMCPConfig:
    """Clone or probe a GitHub repo and return NormalizedMCPConfig."""
    logger.info("analyzing_github_repo", repo_url=url)

    from vendor.services import repo_analyzer
    parse_fn = getattr(repo_analyzer, "_parse_github_url", _parse_github_url)
    gh = parse_fn(url)
    scanned: dict[str, Any] = {}
    cloned_successfully = False
    clone_dir = None

    if gh.owner != "unknown":
        raw_fn = getattr(repo_analyzer, "_fetch_github_raw_manifests", _fetch_github_raw_manifests)
        scanned = await raw_fn(gh.owner, gh.repo, branch=gh.branch, subpath=gh.subpath)

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

            target_dir = clone_dir
            if gh.subpath:
                candidate = clone_dir / gh.subpath
                if candidate.is_dir():
                    target_dir = candidate

            scan_dir_fn = getattr(repo_analyzer, "_scan_local_dir", _scan_local_dir)
            scan_src_fn = getattr(repo_analyzer, "_scan_source_files", _scan_source_files)
            scanned = await scan_dir_fn(target_dir)
            scanned["_source_files"] = await scan_src_fn(target_dir)

            cloned_successfully = True
        except Exception as exc:
            logger.warning("git_clone_failed", repo_url=url, error=str(exc))

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

    try:
        build_fn = getattr(repo_analyzer, "_build_normalized_config", _build_normalized_config)
        config = build_fn(
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
    """Probe a remote HTTP endpoint and return NormalizedMCPConfig."""
    logger.info("analyzing_remote_http", endpoint=url)
    try:
        from vendor.services.mcp_detect import detect_mcp_server
        detection = await detect_mcp_server(url)

        transport = detection["transport"]
        endpoint = detection["endpoint"]
        auth_type = detection["auth_type"]
        transport_confidence = detection.get("transport_confidence", 0.5)
        transport_evidence = detection.get("transport_evidence", [])
        oauth = detection.get("oauth") or {}
        hints = detection.get("hints", [])

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

        if not auth_fields and auth_type not in ("none", "env", "unknown"):
            from vendor.services import repo_analyzer
            fields_fn = getattr(repo_analyzer, "_build_auth_fields_for_auth_type", _build_auth_fields_for_auth_type)
            auth_fields = fields_fn(auth_type)

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

    from vendor.services import repo_analyzer
    scan_dir_fn = getattr(repo_analyzer, "_scan_local_dir", _scan_local_dir)
    scan_file_fn = getattr(repo_analyzer, "_scan_local_file", _scan_local_file)
    scan_src_fn = getattr(repo_analyzer, "_scan_source_files", _scan_source_files)

    if local_path.is_dir():
        scanned = await scan_dir_fn(local_path)
        scanned["_source_files"] = await scan_src_fn(local_path)
    else:
        scanned = await scan_file_fn(local_path)

    build_fn = getattr(repo_analyzer, "_build_normalized_config", _build_normalized_config)
    return build_fn(
        scanned=scanned,
        source_type="local",
        source_url=path,
    )


def _build_normalized_config(
    scanned: dict[str, Any],
    source_type: str,
    source_url: str,
    source_repo: str = "",
    source_branch: str = "main",
    source_subpath: str | None = None,
) -> NormalizedMCPConfig:
    """Build NormalizedMCPConfig from a dict of scanned manifests."""
    from vendor.services import repo_analyzer
    collect_ev_fn = getattr(repo_analyzer, "_collect_transport_evidence", _collect_transport_evidence)
    best_trans_fn = getattr(repo_analyzer, "_best_transport", _best_transport)
    infer_fn = getattr(repo_analyzer, "_infer_transport_and_runtime", _infer_transport_and_runtime)
    detect_auth_fn = getattr(repo_analyzer, "_detect_auth_type", _detect_auth_type)
    extract_env_fn = getattr(repo_analyzer, "_extract_env_vars", _extract_env_vars)
    build_fields_fn = getattr(repo_analyzer, "_build_auth_fields", _build_auth_fields)
    build_fields_type_fn = getattr(repo_analyzer, "_build_auth_fields_for_auth_type", _build_auth_fields_for_auth_type)

    evidence_list = collect_ev_fn(scanned)
    transport_type, transport_confidence, transport_evidence = best_trans_fn(evidence_list)

    legacy_transport, runtime_type, raw_command, remote_endpoint = infer_fn(scanned)

    if transport_confidence >= 0.60 and transport_type != "unknown":
        final_transport = transport_type
    else:
        final_transport = legacy_transport
        if not transport_evidence and final_transport != "unknown":
            transport_evidence = [TransportEvidence(
                source="heuristic",
                reason=f"Inferred from manifest structure as {final_transport}",
            )]

    working_directory: str | None = None
    if source_subpath:
        working_directory = source_subpath

    command: str | None = None
    args: list[str] = []
    if raw_command:
        parts = raw_command.split()
        if parts:
            if source_subpath and parts[0].startswith(source_subpath + "/"):
                parts[0] = parts[0][len(source_subpath) + 1:]
            command = parts[0]
            args = parts[1:]

    auth_type = detect_auth_fn(scanned, remote_endpoint)
    env_vars = extract_env_fn(scanned)
    if auth_type == "oauth2" or any(v.endswith("_OAUTH_CREDENTIALS") or v.endswith("_CREDENTIALS_JSON") for v in env_vars):
        auth_type = "oauth2"

    auth_fields = build_fields_fn(env_vars)
    if not auth_fields and auth_type not in ("none", "unknown"):
        auth_fields = build_fields_type_fn(
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


async def _analyze_github_repo(url: str, parsed, root: Path) -> AnalyzeRepoResponse:
    from vendor.services import repo_analyzer
    gh_fn = getattr(repo_analyzer, "_analyze_github_repo_normalized", _analyze_github_repo_normalized)
    return (await gh_fn(url, root)).to_analyze_repo_response()


async def _analyze_remote_http(url: str, parsed, root: Path) -> AnalyzeRepoResponse:
    from vendor.services import repo_analyzer
    remote_fn = getattr(repo_analyzer, "_analyze_remote_http_normalized", _analyze_remote_http_normalized)
    return (await remote_fn(url, root)).to_analyze_repo_response()


async def _analyze_local_path(path: str, parsed, root: Path) -> AnalyzeRepoResponse:
    from vendor.services import repo_analyzer
    local_fn = getattr(repo_analyzer, "_analyze_local_path_normalized", _analyze_local_path_normalized)
    return (await local_fn(path, root)).to_analyze_repo_response()
