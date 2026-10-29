"""Get every stdio MCP server built from GitHub ready before a run needs it.

A first ``npm install`` / ``uv sync`` of a server takes minutes – longer than a run waits for a tool to start
(``TOOL_SESSION_CONNECT_TIMEOUT_SECONDS``), so a run right after a restart got "didn't start within 120s" from
Tavily, Job Scout and JobSpy. The worker calls ``warm_all`` in the background when it starts; a checkout already
prepared (``stdio._PREPARED_MARKER``, kept in the ``mcp_repos`` volume) costs nothing.

By hand, in the worker container:

    cd apps/backend && python -m vendor.services.mcp_client.warm
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import sys
from pathlib import Path

logger = logging.getLogger("vendor.mcp_client")

_UV_SYNC_TIMEOUT = 300


async def _servers() -> list[tuple[str, str, str]]:
    """(name, command, source_repo_url) of the stdio servers that run from a GitHub checkout."""
    from sqlalchemy import select
    from src.db.session import SessionLocal

    from vendor.models import VendorMCPServer
    from vendor.services.mcp_client.stdio import _PACKAGE_RUNNER_COMMANDS

    async with SessionLocal() as db:
        rows = (await db.execute(select(VendorMCPServer).where(VendorMCPServer.transport == "stdio"))).scalars().all()
    out = []
    for s in rows:
        command = (s.command or "").strip()
        if not command or not s.source_repo_url or command.split()[0] in _PACKAGE_RUNNER_COMMANDS:
            continue
        if s.args:
            command += " " + " ".join(shlex.quote(str(a)) for a in s.args)
        out.append((s.name, command, s.source_repo_url))
    return out


async def warm_one(name: str, command: str, source_repo_url: str) -> bool:
    from vendor.services.mcp_client.stdio import _describe_build_error, _prepare_local_repo_stdio, _run

    try:
        binary, args, _cwd = await _prepare_local_repo_stdio(command, source_repo_url)
        # A Python server runs as "uv run --directory <checkout> …": its venv is made on the first run – do it now.
        if binary == "uv" and args[:2] == ["run", "--directory"]:
            project = Path(args[2])
            if not (project / ".venv").is_dir():
                await _run(["uv", "sync", "--directory", str(project)], capture_output=True,
                           timeout=_UV_SYNC_TIMEOUT, check=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_warm_failed %s: %s", name, _describe_build_error(exc))
        return False
    logger.info("mcp_warm_ready %s", name)
    return True


async def warm_all() -> tuple[int, int]:
    """Prepare each server in turn (several npm installs at once only slow each other down). (ready, failed)."""
    try:
        servers = await _servers()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_warm_skipped: %s", exc)
        return 0, 0
    ok = 0
    for name, command, url in servers:
        ok += await warm_one(name, command, url)
    return ok, len(servers) - ok


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[5]
    for p in (root, root / "apps" / "auth", root / "apps" / "backend"):
        sys.path.insert(0, str(p))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import knowledge.models  # noqa: F401
    import vendor.models  # noqa: F401

    ready, failed = asyncio.run(warm_all())
    print(f"MCP servers ready: {ready}, failed: {failed}")
    sys.exit(1 if failed else 0)
