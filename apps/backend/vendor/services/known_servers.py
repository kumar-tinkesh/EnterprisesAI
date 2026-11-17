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
* jimsimoy/gmail-mcp — needs GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN, and the refresh
  token only comes from a browser consent. Analysis also turned tool arguments (DRAFT_ID, THREAD_ID) into
  fields. So it is an OAuth server with Google's fixed endpoints: the admin gives the OAuth client's ID and
  secret, every person signs in with Google ("Connect via OAuth"), and the tokens that sign-in stores
  (refresh_token, client_id, client_secret) are passed on under the GMAIL_* names it reads. It runs at
  GMAIL_ACCESS_LEVEL=FULL (read, drafts, send, organize); the agents' "ask before tools run" still asks
  before a sending or deleting tool.
* nspady/google-calendar-mcp — reads GOOGLE_OAUTH_CREDENTIALS as the *path* of a client JSON file and its
  tokens from a tokens.json written by its own browser sign-in; analysis offered GOOGLE_OAUTH_CREDENTIALS
  and GOOGLE_SERVICE_ACCOUNT_KEY as fields, so the client ID and secret typed into them were read as file
  paths ("could not be read as JSON: ENOENT"). Same OAuth shape as Gmail: the admin gives the client ID and
  secret, every person signs in with Google, and at launch both files are written from what is stored
  (``mcp_client.stdio.build_stdio_params``). An ID and secret already saved under the old names are passed
  on under the new ones, and the old names are never passed on as paths (``drop``).
* xing5/mcp-google-sheets — Python, run from its PyPI package. Same OAuth shape: it reads a google-auth
  token file (TOKEN_PATH, written at launch with the refresh token, client ID and secret) and without one
  starts a browser sign-in on the server, so a person signs in with Google ("Connect via OAuth") first.
  It asks for spreadsheets + full drive (it lists and shares spreadsheets through Drive). Its package
  doesn't pin ``mcp`` and fails on mcp 2.x, so it runs with ``mcp<2``.

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
    {
        "repo": "jimsimoy/gmail-mcp",
        "env_vars": {"GMAIL_ACCESS_LEVEL": "FULL"},
        "auth_type": "oauth2",
        "oauth": {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            # The server's own consent set (gmail_mcp.access.CONSENT_SCOPES) — never https://mail.google.com/.
            "scopes_supported": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
            # Google returns a refresh token only for offline access, and again only on a fresh consent.
            "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
        },
        "fields": [
            {"name": "GMAIL_CLIENT_ID", "label": "Google OAuth Client ID", "type": "string", "required": True, "location": "env"},
            {"name": "GMAIL_CLIENT_SECRET", "label": "Google OAuth Client Secret", "type": "secret", "required": True, "location": "env"},
        ],
        "aliases": {"refresh_token": "GMAIL_REFRESH_TOKEN", "client_id": "GMAIL_CLIENT_ID", "client_secret": "GMAIL_CLIENT_SECRET"},
    },
    {
        "repo": "nspady/google-calendar-mcp",
        "env_vars": {},
        "auth_type": "oauth2",
        "oauth": {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            # The server's own sign-in asks for exactly this (src/auth/server.ts).
            "scopes_supported": ["https://www.googleapis.com/auth/calendar"],
            "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
        },
        "fields": [
            {"name": "GOOGLE_CLIENT_ID", "label": "Google OAuth Client ID", "type": "string", "required": True, "location": "env"},
            {"name": "GOOGLE_CLIENT_SECRET", "label": "Google OAuth Client Secret", "type": "secret", "required": True, "location": "env"},
        ],
        "aliases": {
            "refresh_token": "GOOGLE_REFRESH_TOKEN", "client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET",
            "GOOGLE_OAUTH_CREDENTIALS": "GOOGLE_CLIENT_ID", "GOOGLE_SERVICE_ACCOUNT_KEY": "GOOGLE_CLIENT_SECRET",
        },
        "drop": ["GOOGLE_OAUTH_CREDENTIALS", "GOOGLE_SERVICE_ACCOUNT_KEY"],
    },
    {
        "repo": "xing5/mcp-google-sheets",
        "command": "uvx",
        # It imports mcp.server.fastmcp and doesn't pin mcp; 2.x renamed it, so it can't start.
        "args": ["--with", "mcp<2", "mcp-google-sheets@0.6.3"],
        "runtime_type": "python",
        "env_vars": {},
        "auth_type": "oauth2",
        "oauth": {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            # The server's own SCOPES (src/mcp_google_sheets/server.py).
            "scopes_supported": ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
            "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
        },
        "fields": [
            {"name": "GOOGLE_CLIENT_ID", "label": "Google OAuth Client ID", "type": "string", "required": True, "location": "env"},
            {"name": "GOOGLE_CLIENT_SECRET", "label": "Google OAuth Client Secret", "type": "secret", "required": True, "location": "env"},
        ],
        "aliases": {"refresh_token": "GOOGLE_REFRESH_TOKEN", "client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET"},
        # Paths analysis offered as fields; a value typed into one would be read as a file.
        "drop": ["CREDENTIALS_PATH", "TOKEN_PATH", "SERVICE_ACCOUNT_PATH", "CREDENTIALS_CONFIG"],
    },
]


def profile_for(*places: str | None) -> dict | None:
    for p in PROFILES:
        if any(p["repo"] in (place or "").lower() for place in places):
            return p
    return None


def _auth_type(p: dict) -> str:
    return p.get("auth_type") or ("env" if p["fields"] else "none")


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
                        "credential_fields": fields, "required_env": [], **({"oauth": dict(p["oauth"])} if "oauth" in p else {})},
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
    for name in p.get("drop", []):
        out.pop(name, None)
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
