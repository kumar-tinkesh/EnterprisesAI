"""File, directory, GitHub, and HTTP scanner functions for repo_analyzer."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from httpx import AsyncClient
import structlog

logger = structlog.get_logger(__name__)


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


async def _scan_source_files(dir_path: Path) -> dict[str, str]:
    """Scan .ts, .js, .py, .go, .rs source files for transport patterns."""
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


async def _scan_local_dir(dir_path: Path) -> dict[str, Any]:
    """Scan a local directory for MCP server manifests."""
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


async def _fetch_github_raw_manifests(
    owner: str,
    repo: str,
    branch: str = "main",
    subpath: str | None = None,
) -> dict[str, Any]:
    """Fetch repository manifest files over HTTPS raw API when git is not available."""
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


# Registry of runtime manifest scanners (decoupled, pluggable)
_SCANNERS = {
    "github": lambda path, root: _scan_github_repo(path, root),
    "remote_http": lambda path, root: _scan_remote_http(path, root),
    "local_file": lambda path, root: _scan_local_file(path, root),
}
