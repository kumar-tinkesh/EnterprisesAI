"""LinkedIn (stickerdaniel/linkedin-mcp-server) signed in with each user's own ``li_at`` cookie.

Ported from the AI Marketplace (connectors/resolve/linkedin_session.py). The server never takes a cookie
from the environment: it reads a session from an "auth root" on disk. In a container it never logs in
itself; it starts a fresh headless Chromium, imports ``li_at`` from ``<root>/cookies.json`` and checks it
against the feed (its "foreign runtime bridge"). That path needs three things:

  <root>/cookies.json        portable cookies; li_at is the one that matters
  <root>/source-state.json   says the session was made on another runtime
  <root>/profile/            non-empty source profile (never opened here)

so one root is written per cookie and the server is pointed at it with ``--user-data-dir <root>/profile``.
The layout is upstream's, which is why the version is pinned (``PACKAGE``, docker/Dockerfile.backend) —
re-check this module when bumping it.

Repo analysis reads the server's README and offers PROXY_USERNAME / PROXY_PASSWORD as its credentials;
those are an optional proxy, and a proxy password without a proxy server makes it exit at start
("proxy_password is set without proxy_server"). The one field that matters is ``LI_AT``: the vendor
admin gives one to test the server (stored as the shared row, used for that test only), and each user
gives their own to connect — a run always uses the runner's own. ``apply_to_analysis`` sets that at
analysis (so the add-server preview and registration show it); ``apply_profile`` on a server row, for
one registered before this existed (also migration d7e8f9a0b1c2).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone

from vendor.services.mcp_auth.crypto import McpAuthError

AUTH_TYPE = "linkedin_cookie"
COOKIE_FIELD = "LI_AT"
REPO = "stickerdaniel/linkedin-mcp-server"
PACKAGE = "mcp-server-linkedin==4.26.0"
# Installed into the image as a uv tool (docker/Dockerfile.backend); uvx is the fallback outside it.
BINARY = "mcp-server-linkedin"
ENV = {"HEADLESS": "true", "LINKEDIN_MCP_CHECK_FOR_UPDATES": "false"}

FIELD = {
    "name": COOKIE_FIELD,
    "label": "LinkedIn li_at cookie",
    "type": "secret",
    "required": True,
    "location": "env",
}

# Any value other than the current runtime id ("linux-x86_64-container") makes the server bridge from
# cookies.json instead of opening profile/.
_SOURCE_RUNTIME_ID = "enterpriseai-cookie-import"


def is_linkedin(server) -> bool:
    places = (server.source_repo_url, server.source_repo, server.server_url)
    return (server.auth_config or {}).get("auth_type") == AUTH_TYPE or any(REPO in (p or "").lower() for p in places)


def apply_profile(server) -> bool:
    """Make a LinkedIn server ask for ``li_at`` only (admin and users alike). True if it changed."""
    if not is_linkedin(server):
        return False
    auth_config = {
        **(server.auth_config or {}),
        "auth_type": AUTH_TYPE,
        "transport": "stdio",
        "credential_fields": [dict(FIELD)],
        "required_env": [],
    }
    wanted = {"auth_config": auth_config, "auth_type": AUTH_TYPE, "auth_schema": {"fields": [dict(FIELD)]},
              "env_vars": {}, "transport": "stdio"}
    changed = [k for k, v in wanted.items() if getattr(server, k) != v]
    for k in changed:
        setattr(server, k, wanted[k])
    return bool(changed)


def apply_to_analysis(source_url: str, result) -> None:
    """A repo analysis (NormalizedMCPConfig) of this server asks for ``li_at`` instead of PROXY_*."""
    if REPO not in (source_url or "").lower():
        return
    from vendor.services.repo_analyzer.types import AuthField

    result.auth_type = AUTH_TYPE
    result.transport_type = "stdio"
    result.auth_fields = [AuthField(**FIELD)]
    result.required_env = []
    result.required_env_vars = [COOKIE_FIELD]


def normalize_li_at(raw: str | None) -> str:
    """Accept the value as people paste it: bare, quoted, or as ``li_at=...``."""
    value = (raw or "").strip().strip('"').strip("'").strip()
    if value.lower().startswith("li_at="):
        value = value[len("li_at="):].strip()
    return value.rstrip(";").strip()


def _write_json(path: str, data) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def session_root() -> str:
    return os.path.join(tempfile.gettempdir(), "mcp_linkedin")


def write_session(raw_cookie: str) -> str:
    """Materialise the auth root for this cookie (once) and return its profile dir."""
    li_at = normalize_li_at(raw_cookie)
    if not li_at:
        raise McpAuthError("Paste your LinkedIn li_at cookie to connect LinkedIn.")

    key = hashlib.sha256(li_at.encode()).hexdigest()[:24]
    root = os.path.join(session_root(), key)
    profile = os.path.join(root, "profile")
    cookies_path = os.path.join(root, "cookies.json")
    state_path = os.path.join(root, "source-state.json")
    if os.path.exists(state_path) and os.path.exists(cookies_path):
        return profile

    os.makedirs(profile, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    # profile_exists() wants the directory non-empty; Chromium writes this marker itself, so it is the
    # least surprising thing to put there.
    open(os.path.join(profile, "First Run"), "a").close()

    _write_json(cookies_path, [{
        "name": "li_at",
        "value": li_at,
        "domain": ".linkedin.com",
        "path": "/",
        "expires": int(time.time()) + 365 * 24 * 3600,
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    }])
    # Written last: its presence is what marks the root complete (see above).
    _write_json(state_path, {
        "version": 1,
        "source_runtime_id": _SOURCE_RUNTIME_ID,
        "login_generation": key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile_path": profile,
        "cookies_path": cookies_path,
    })
    return profile


def command() -> str:
    return BINARY if shutil.which(BINARY) else f"uvx --python 3.12 --from {PACKAGE} {BINARY}"


def launch_config(credentials: dict[str, str] | None, *, for_user: bool) -> dict:
    """The stdio launch for this server: the pinned package, its session dir, and nothing from the
    detected repo (no clone, no PROXY_* env). ``for_user``: a user's connect or run, which needs their
    own cookie; the vendor admin's test uses theirs when given (listing tools needs no session)."""
    li_at = normalize_li_at((credentials or {}).get(COOKIE_FIELD) or (credentials or {}).get(COOKIE_FIELD.lower()))
    if for_user and not li_at:
        raise McpAuthError("Paste your LinkedIn li_at cookie to connect LinkedIn.")
    args = ["--claim-profile-root"]
    if li_at:
        args += ["--user-data-dir", write_session(li_at)]
    return {
        "command": command(),
        "args": args,
        "working_directory": None,
        "source_repo_url": None,
        "env_vars": dict(ENV),
        # The cookie reaches the server as the session dir only, never as an env var.
        "credentials": {},
    }


__all__ = [
    "AUTH_TYPE", "COOKIE_FIELD", "PACKAGE", "apply_profile", "apply_to_analysis", "is_linkedin", "launch_config",
    "normalize_li_at", "session_root", "write_session",
]
