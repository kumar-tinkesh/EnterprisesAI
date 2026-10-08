"""A real MCP server for the tool-runtime tests.

    python demo_mcp_server.py                  # stdio
    python demo_mcp_server.py http <port>      # streamable HTTP on 127.0.0.1:<port>/mcp

Each tool exercises one runtime path: plain results, structured output, the
per-user environment, data-changing tools, slow calls, tool errors, and a
server process that dies mid-call.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

server = MCPServer("demo")


class Identity(TypedDict):
    home: str | None
    token: str | None
    pid: int


def _home() -> Path:
    return Path(os.environ.get("HOME", "."))


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@server.tool(structured_output=True)
def add_numbers(a: int, b: int) -> dict[str, int]:
    """Add two integers."""
    return {"sum": a + b}


@server.tool(annotations=ToolAnnotations(read_only_hint=True), structured_output=True)
def whoami() -> Identity:
    """Report this process's HOME and the credential it was started with."""
    return {"home": os.environ.get("HOME"), "token": os.environ.get("DEMO_TOKEN"), "pid": os.getpid()}


@server.tool()
def send_note(text: str) -> str:
    """Append a note to notes.txt in this user's home."""
    notes = _home() / "notes.txt"
    with notes.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return f"{len(notes.read_text(encoding='utf-8').splitlines())} notes"


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
def wipe() -> str:
    """Remove every note."""
    (_home() / "notes.txt").unlink(missing_ok=True)
    return "wiped"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
async def wait_for(seconds: float) -> str:
    """Sleep, then answer (without blocking the server's other calls)."""
    await asyncio.sleep(seconds)
    return "done"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def fail() -> str:
    """Always fails, with a message meant for the caller."""
    raise ToolError("boom from the demo server")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_flaky() -> str:
    """Kills the server process the first time (per user), answers after that."""
    marker = _home() / "flaky.marker"
    if not marker.exists():
        marker.write_text("1", encoding="utf-8")
        os._exit(1)
    return "recovered"


@server.tool()
def email_report(to: str, body: str) -> str:
    """Email a report to someone (records it in notes.txt)."""
    with (_home() / "notes.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"to={to} body={body}\n")
    return f"emailed {to}"


@server.tool()
async def post_slowly(text: str, seconds: float) -> str:
    """A data-changing tool that does its work, then takes a while to answer."""
    with (_home() / "notes.txt").open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    await asyncio.sleep(seconds)
    return "posted"


@server.tool()
def post_and_crash(text: str) -> str:
    """A data-changing tool whose process dies mid-call."""
    os._exit(1)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run()
