"""Instagram (thenavidm/instagram-mcp): "Connect with Instagram" through Meta's Unified Login, or a pasted token.

The server reads three things from its environment: ``IG_ACCESS_TOKEN``, ``IG_USER_ID`` (the Instagram
professional account's id) and ``IG_HOST`` — ``graph.facebook.com`` for a Facebook-side token (``EA…``:
a Facebook user or system-user token) and ``graph.instagram.com`` for an Instagram Login token (``IG…``).
Repo analysis also offered ACCESS_TOKEN and CLIENT_SECRET from its README; it reads neither. So the
fields are the two it does read, and ``IG_HOST`` is set from the token at launch (``launch_credentials``)
instead of being one more thing to get right.

Connect with Instagram (Meta's "Instagram API with Unified Login", the setup new Meta apps get):

1. The vendor admin saves the Meta app's ID, its secret and the login configuration's ID (Meta app →
   Instagram API → "Configure your app"), and registers the callback URL shown with them in that
   configuration. The secret goes on the server's shared credential row, encrypted, merged with what is
   there; the ID and configuration ID (not secrets) go on ``auth_config["instagram"]`` so the catalog can
   tell people the button works without decrypting anything.
2. A person presses the button: Facebook Login for Business's dialog opens with that configuration, and
   they sign in with Instagram or Facebook and pick their Instagram professional account.
3. The callback exchanges the code (``graph.facebook.com/oauth/access_token``) for a Business Integration
   System User token, finds the account with ``/me/assigned_instagram_accounts``, and stores token, id,
   username and expiry as that person's own credential row. Nothing is pasted.

Until Meta's App Review, only people with a role on the app (Instagram testers) can finish the sign-in.
The token's lifetime is the configuration's; when it stops working the person connects again.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from vendor.services.mcp_auth.crypto import McpAuthError

AUTH_TYPE = "instagram_meta"
REPO = "thenavidm/instagram-mcp"
GRAPH_VERSION = "v27.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
DIALOG = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"

TOKEN, USER_ID, HOST = "IG_ACCESS_TOKEN", "IG_USER_ID", "IG_HOST"
FIELDS = [
    {"name": TOKEN, "label": "Access token (starts with EAA or IG)", "type": "secret", "required": True, "location": "env"},
    {"name": USER_ID, "label": "Instagram account ID (numbers only)", "type": "string", "required": True, "location": "env"},
]
# Shared-row keys for the Meta app (never passed to the server).
APP_ID, APP_SECRET = "meta_app_id", "meta_app_secret"
# What a sign-in stores besides the two fields.
USERNAME, EXPIRES_AT, SIGNED_IN = "IG_USERNAME", "IG_EXPIRES_AT", "IG_SIGNED_IN"
# README-detected names the server never reads.
_UNUSED = ("ACCESS_TOKEN", "CLIENT_SECRET", "IG_HOST")
_TIMEOUT = 15.0


def is_instagram(server) -> bool:
    places = (getattr(server, "source_repo_url", None), getattr(server, "source_repo", None), getattr(server, "server_url", None))
    return (server.auth_config or {}).get("auth_type") == AUTH_TYPE or any(REPO in (p or "").lower() for p in places)


def apply_profile(server) -> bool:
    """Ask for the token and the account id only, and keep the sign-in setup. True if it changed."""
    if not is_instagram(server):
        return False
    auth_config = {
        **(server.auth_config or {}),
        "auth_type": AUTH_TYPE,
        "transport": "stdio",
        "credential_fields": [dict(f) for f in FIELDS],
        "required_env": [],
    }
    env_vars = {k: v for k, v in (server.env_vars or {}).items() if k.upper() not in _UNUSED and k not in (TOKEN, USER_ID)}
    wanted = {"auth_config": auth_config, "auth_type": AUTH_TYPE, "auth_schema": {"fields": [dict(f) for f in FIELDS]},
              "env_vars": env_vars, "transport": "stdio"}
    changed = [k for k, v in wanted.items() if getattr(server, k) != v]
    for k in changed:
        setattr(server, k, wanted[k])
    return bool(changed)


def apply_to_analysis(source_url: str, result) -> None:
    """A repo analysis of this server asks for the two fields it reads."""
    if REPO not in (source_url or "").lower():
        return
    from vendor.services.repo_analyzer.types import AuthField

    result.auth_type = AUTH_TYPE
    result.transport_type = "stdio"
    result.auth_fields = [AuthField(**f) for f in FIELDS]
    result.required_env = []
    result.required_env_vars = [TOKEN, USER_ID]


# ── a pasted token ───────────────────────────────────────────────────────────


def clean_token(raw: str | None) -> str:
    """As people paste it: quoted, with "Bearer ", or with spaces and line breaks from a copy."""
    value = re.sub(r"\s+", "", (raw or "").strip().strip('"').strip("'"))
    if value.lower().startswith("bearer"):
        value = value[len("bearer"):]
    return value


def clean_user_id(raw: str | None) -> str:
    return re.sub(r"\D", "", raw or "")


def host_for(token: str) -> str:
    """Instagram Login tokens (IG…) are for graph.instagram.com; every Facebook-side one (EA…) for graph.facebook.com."""
    return "graph.instagram.com" if token.startswith("IG") else "graph.facebook.com"


def token_problem(token: str) -> str | None:
    """Why a pasted value can't be an access token, or None."""
    if not token:
        return "Paste the access token."
    if token.startswith("AQ") or "code=" in token:
        return "That looks like the one-time code from a sign-in, not an access token. Use the token Meta shows you."
    if len(token) < 60:
        return "That's too short for an access token. Copy the whole token."
    if not re.fullmatch(r"[A-Za-z0-9_\-|.]+", token):
        return "The token has characters a token never has. Copy it again, without anything around it."
    return None


def launch_credentials(credentials: dict[str, str] | None) -> dict[str, str]:
    """What the server is started with: token, account id and the host for that token — nothing else
    (never the Meta app's secret, which shares the admin's row)."""
    creds = credentials or {}
    token = clean_token(creds.get(TOKEN) or creds.get(TOKEN.lower()))
    user_id = clean_user_id(creds.get(USER_ID) or creds.get(USER_ID.lower()))
    out = {}
    if token:
        out[TOKEN] = token
        out[HOST] = host_for(token)
    if user_id:
        out[USER_ID] = user_id
    return out


def check_pasted(credentials: dict[str, str] | None) -> dict[str, str]:
    """A person's pasted token and id, cleaned, or McpAuthError saying what's wrong with them."""
    creds = credentials or {}
    token = clean_token(creds.get(TOKEN))
    problem = token_problem(token)
    if problem:
        raise McpAuthError(problem)
    user_id = clean_user_id(creds.get(USER_ID))
    if not user_id:
        raise McpAuthError("Add your Instagram account ID (numbers only, e.g. 17841…).")
    return {TOKEN: token, USER_ID: user_id}


# ── Connect with Instagram (Unified Login) ───────────────────────────────────


def sign_in_setup(server) -> dict:
    """{app_id, config_id, has_secret} as the admin saved them ({} if never)."""
    return dict((server.auth_config or {}).get("instagram") or {})


def sign_in_ready(server) -> bool:
    s = sign_in_setup(server)
    return bool(s.get("app_id") and s.get("config_id") and s.get("has_secret"))


def authorize_url(*, app_id: str, config_id: str, redirect_uri: str, state: str) -> str:
    """Facebook Login for Business with the app's Instagram configuration; the code grant is what
    returns a system-user token."""
    return f"{DIALOG}?" + urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "config_id": config_id,
        "response_type": "code",
        "override_default_response_type": "true",
    })


def _client() -> httpx.AsyncClient:
    from vendor.services import mcp_auth

    factory = getattr(mcp_auth, "_new_client", None)
    return factory() if factory else httpx.AsyncClient(timeout=_TIMEOUT)


def _meta_error(response: httpx.Response) -> str:
    try:
        err = response.json().get("error") or {}
        return err.get("message") or response.text[:200]
    except Exception:  # noqa: BLE001
        return response.text[:200]


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, str], what: str) -> dict[str, Any]:
    response = await client.get(url, params=params)
    if response.status_code != 200:
        raise McpAuthError(f"Meta didn't {what}: {_meta_error(response)}")
    return response.json()


async def complete(*, app_id: str, app_secret: str, code: str, redirect_uri: str, now: datetime | None = None) -> dict[str, str]:
    """The code from the callback -> this person's credential row (token, account id, username, expiry)."""
    code = (code or "").split("#", 1)[0]
    async with _client() as client:
        token = await _get(
            client, f"{GRAPH}/oauth/access_token",
            {"client_id": app_id, "client_secret": app_secret, "redirect_uri": redirect_uri, "code": code},
            "give a token for that sign-in",
        )
        access_token = token.get("access_token") or ""
        if not access_token:
            raise McpAuthError("Meta's answer had no access token. Try connecting again.")
        accounts = await _get(
            client, f"{GRAPH}/me/assigned_instagram_accounts",
            {"fields": "id,username", "access_token": access_token},
            "list the Instagram accounts you shared",
        )
        rows = [a for a in accounts.get("data") or [] if a.get("id")]
        if not rows:
            raise McpAuthError(
                "No Instagram account came with that sign-in. Connect again and pick your Instagram "
                "professional (Business or Creator) account when Meta asks."
            )
        account = rows[0]
        username = account.get("username") or ""
        if not username:
            try:
                username = (await _get(client, f"{GRAPH}/{account['id']}", {"fields": "username", "access_token": access_token},
                                       "read the account's username")).get("username") or ""
            except McpAuthError:
                username = ""
    expires_in = int(token.get("expires_in") or 0)
    expires_at = ((now or datetime.now(timezone.utc)) + timedelta(seconds=expires_in)).isoformat() if expires_in else ""
    return {TOKEN: access_token, USER_ID: str(account["id"]), USERNAME: username, EXPIRES_AT: expires_at, SIGNED_IN: "meta"}


# ── Tools this platform adds to the server ───────────────────────────────────
#
# The server can reply to a comment but not leave a new one on a post, though Graph API can
# (POST /{media-id}/comments, instagram_manage_comments). So the platform adds that one tool itself: it is
# listed with the server's own tools when the server is tested (``LOCAL_TOOLS``), and invoke_tool runs it here
# (``call_local``) with the person's own token instead of sending it to the server. Everything else about it —
# who may use it, asking first (it changes the account: risk "edit"), the admin turning it off — is the same as
# for the server's tools.

COMMENT_TOOL = "comment_on_post"
LOCAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": COMMENT_TOOL,
        "description": (
            "Leave a new comment on one of your own posts (a top-level comment; reply_to_comment answers an existing "
            "one). media_id: the post's numeric id, its link (instagram.com/p/<code>/) or that code. The comment is "
            "public at once."
        ),
        "input_schema": {
            "type": "object",
            "title": "comment_on_postArguments",
            "properties": {
                "media_id": {"type": "string", "title": "Media Id"},
                "message": {"type": "string", "title": "Message"},
            },
            "required": ["media_id", "message"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
]
LOCAL_TOOL_NAMES = frozenset(t["name"] for t in LOCAL_TOOLS)
# A post's link: instagram.com/p/<code>/, /reel/<code>/, /tv/<code>/ (optionally under a username).
_POST_LINK = re.compile(r"instagram\.com/(?:[^/?#]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
_MEDIA_PAGES = 4  # x 50 posts: how far back a link is looked up


def is_local_tool(server, tool_name: str) -> bool:
    return tool_name in LOCAL_TOOL_NAMES and is_instagram(server)


def _graph_error(response: httpx.Response) -> str:
    """Meta's message with its code, so a permission problem (10, 200) can be told from a wrong id (100)."""
    try:
        err = response.json().get("error") or {}
    except Exception:  # noqa: BLE001
        return response.text[:200]
    code = err.get("code")
    return f"{err.get('message') or response.text[:200]}" + (f" (code {code})" if code is not None else "")


async def _media_id(client: httpx.AsyncClient, base: str, token: str, user_id: str, ref: str) -> str:
    """A numeric id as is; a link or its code -> the id of the account's post with that permalink."""
    ref = (ref or "").strip()
    if ref.isdigit():
        return ref
    match = _POST_LINK.search(ref)
    code = match.group(1) if match else ref.strip("/ ")
    if not code or not re.fullmatch(r"[A-Za-z0-9_-]+", code):
        raise McpAuthError("media_id must be the post's id, its link or the code in its link.")
    if not user_id:
        raise McpAuthError("Your Instagram account id is missing from the connection, so the link can't be looked up. Use the post's numeric id.")
    url: str | None = f"{base}/{user_id}/media"
    params: dict[str, str] | None = {"fields": "id,permalink", "limit": "50", "access_token": token}
    for _ in range(_MEDIA_PAGES):
        if not url:
            break
        response = await client.get(url, params=params)
        if response.status_code != 200:
            raise McpAuthError(f"Couldn't look the post up: {_graph_error(response)}")
        body = response.json()
        for item in body.get("data") or []:
            if f"/{code}/" in (item.get("permalink") or "").rstrip("/") + "/":
                return str(item["id"])
        url, params = (body.get("paging") or {}).get("next"), None  # the next link carries its own query
    raise McpAuthError(f"No post of yours has the link code {code}. Only your own posts can be commented on here.")


async def call_local(tool_name: str, arguments: dict[str, Any], credentials: dict[str, str]) -> tuple[bool, str]:
    """Run one of LOCAL_TOOLS as the person whose launch credentials these are -> (is_error, text)."""
    import json

    if tool_name != COMMENT_TOOL:
        return True, f"Unknown tool {tool_name}."
    token = clean_token(credentials.get(TOKEN))
    if not token:
        return True, "Connect your Instagram account first."
    base = f"https://{credentials.get(HOST) or host_for(token)}/{GRAPH_VERSION}"
    message = str(arguments.get("message") or "").strip()
    if not message:
        return True, "message is empty: say what the comment should say."
    async with _client() as client:
        try:
            media_id = await _media_id(client, base, token, clean_user_id(credentials.get(USER_ID)), str(arguments.get("media_id") or ""))
        except McpAuthError as exc:
            return True, str(exc)
        response = await client.post(f"{base}/{media_id}/comments", data={"message": message, "access_token": token})
    if response.status_code != 200:
        return True, f"Instagram didn't post the comment: {_graph_error(response)}"
    return False, json.dumps({"id": response.json().get("id"), "media_id": media_id, "message": message})


__all__ = [
    "APP_ID", "APP_SECRET", "AUTH_TYPE", "FIELDS", "TOKEN", "USER_ID", "USERNAME", "apply_profile", "apply_to_analysis",
    "authorize_url", "check_pasted", "clean_token", "complete", "host_for", "is_instagram", "launch_credentials",
    "COMMENT_TOOL", "LOCAL_TOOLS", "LOCAL_TOOL_NAMES", "call_local", "is_local_tool", "sign_in_ready", "sign_in_setup",
    "token_problem",
]
