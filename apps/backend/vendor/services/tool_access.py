"""Tools a vendor admin turned off on a server (e.g. Instagram's password-based ``unofficial_*``).

Kept on ``auth_config["disabled_tools"]`` — not on the tool rows, which a re-test deletes and
recreates — so it survives every test. A tool that's off is left out wherever tools are offered
(an agent's tools, the builder's tool picker, the AI builder's search) and refused if called.
"""
from __future__ import annotations


def disabled_tools(server) -> set[str]:
    return set(((getattr(server, "auth_config", None) or {}).get("disabled_tools")) or [])


def tool_is_on(server, tool_name: str) -> bool:
    return tool_name not in disabled_tools(server)


__all__ = ["disabled_tools", "tool_is_on"]
