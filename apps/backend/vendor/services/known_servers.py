"""MCP servers whose repo analysis gets the launch or the credentials wrong, set to what works.

Repo analysis clones a GitHub repo, runs its entry point and turns the environment variables its README
mentions into credential fields. For these servers that is wrong, so their row is set to what does run —
the same shape a ``npx``-registered server has, so nothing at run time needs a special case (a
package-runner command is never cloned, see ``mcp_client.stdio._prepare_local_repo_stdio``):

* cyanheads/wikidata-mcp-server — TypeScript; ``dist/`` is built with bun and not in the repo, so
  ``node dist/index.js`` in a clone fails ("Cannot find module …/dist/index.js"). Its README's
  MCP_AUTH_SECRET_KEY / MCP_PUBLIC_URL / OTEL_* are for its HTTP mode and telemetry: no key at all over
  stdio. The npm package (prebuilt) works on the image's Node 22 despite declaring node >= 24.
* makenotion/notion-mcp-server — reads its token from NOTION_TOKEN only; analysis also offered
  AUTH_TOKEN, and a token saved under that name reaches the server as nothing ("the authorization header
  is missing"). One field now, and an AUTH_TOKEN already saved is passed on as NOTION_TOKEN (``aliases``).

Applied at analysis (the add-server preview and registration), when a server is connected or run (an older
row fixes itself) and by migrations e8f9a0b1c2d3 / f0a1b2c3d4e5 for rows already there. LinkedIn has its
own module (``mcp_auth.linkedin``): it needs a per-user session, not just a command.
"""
from __future__ import annotations

PROFILES: list[dict] = [
    {
        "repo": "cyanheads/wikidata-mcp-server",
        "command": "npx",
        "args": ["-y", "@cyanheads/wikidata-mcp-server@0.1.19"],
        "runtime_type": "node",
        "env_vars": {"MCP_LOG_LEVEL": "warning"},
        "fields": [],
    },
    {
        "repo": "makenotion/notion-mcp-server",
        "env_vars": {},
        "fields": [{
            "name": "NOTION_TOKEN", "label": "Notion integration token (ntn_…)", "type": "secret",
            "required": True, "location": "env",
        }],
        "aliases": {"AUTH_TOKEN": "NOTION_TOKEN"},
    },
]


def profile_for(*places: str | None) -> dict | None:
    for p in PROFILES:
        if any(p["repo"] in (place or "").lower() for place in places):
            return p
    return None


def _auth_type(p: dict) -> str:
    return "env" if p["fields"] else "none"


def apply_profile(server) -> bool:
    """Set a known server's row to what works. True if it changed."""
    p = profile_for(server.source_repo_url, server.source_repo, server.server_url)
    if p is None:
        return False
    fields = [dict(f) for f in p["fields"]]
    wanted = {
        "env_vars": dict(p["env_vars"]), "transport": "stdio", "auth_type": _auth_type(p),
        "auth_schema": {"fields": fields},
        "auth_config": {**(server.auth_config or {}), "auth_type": _auth_type(p), "transport": "stdio",
                        "credential_fields": fields, "required_env": []},
    }
    if "command" in p:
        wanted.update(command=p["command"], args=list(p["args"]), runtime_type=p["runtime_type"], working_directory=None)
    changed = [k for k, v in wanted.items() if getattr(server, k) != v]
    for k in changed:
        setattr(server, k, wanted[k])
    return bool(changed)


def alias_credentials(server, credentials: dict[str, str]) -> dict[str, str]:
    """Credentials saved under a name the server doesn't read, passed on under the one it does."""
    p = profile_for(server.source_repo_url, server.source_repo, server.server_url)
    if p is None or not p.get("aliases") or not credentials:
        return credentials
    out = dict(credentials)
    for old, new in p["aliases"].items():
        if out.get(old) and not out.get(new):
            out[new] = out[old]
    return out


def apply_to_analysis(source_url: str, result) -> None:
    """A repo analysis (NormalizedMCPConfig) of a known server: its launch and its credential fields."""
    p = profile_for(source_url)
    if p is None:
        return
    from vendor.services.repo_analyzer.types import AuthField

    if "command" in p:
        result.command = p["command"]
        result.args = list(p["args"])
        result.runtime_type = p["runtime_type"]
        result.working_directory = None
    result.transport_type = "stdio"
    result.auth_type = _auth_type(p)
    result.auth_fields = [AuthField(**f) for f in p["fields"]]
    result.required_env = []
    result.required_env_vars = [f["name"] for f in p["fields"]]


__all__ = ["PROFILES", "alias_credentials", "apply_profile", "apply_to_analysis", "profile_for"]
