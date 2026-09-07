"""Stdio transport execution, repo resolution, and OAuth credential files provisioning for mcp_client."""
from __future__ import annotations

import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

import httpx
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("vendor.mcp_client")

# Package runners resolve their own dependencies/entry points from a registry —
# they never need a local source checkout, so ``source_repo_url`` must NOT
# trigger a repo clone when the command uses one of these.
_PACKAGE_RUNNER_COMMANDS = {
    "npx", "npm", "pnpm", "pnpx", "pip", "pipx", "uv", "uvx",
    "docker", "deno", "bun", "bunx",
}

_REPO_CLONE_TIMEOUT = 120  # seconds
_REPO_BUILD_TIMEOUT = 120


def _python_module_base(root: Path, mod: str) -> Path | None:
    """Return the base dir (repo root or ``src/``) containing ``mod``."""
    rel = mod.replace(".", "/")
    for base in (root, root / "src"):
        if (base / f"{rel}.py").exists() or (base / rel / "__init__.py").exists():
            return base
    return None


def _python_console_entry_code(root: Path, entry: str) -> str | None:
    """Build a ``python -c`` snippet that runs a console-script entry."""
    mod, _, obj_path = entry.partition(":")
    obj_path = obj_path.strip().strip("()")
    mod = mod.strip()
    if not mod or not obj_path:
        return None
    base = _python_module_base(root, mod)
    if base is None:
        return None
    code = (
        "import importlib, sys; "
        f"sys.path.insert(0, {str(base)!r}); "
        f"_o = importlib.import_module({mod!r}); "
    )
    o = "_o"
    for attr in obj_path.split("."):
        attr = attr.strip()
        if attr:
            code += f"{o} = getattr({o}, {attr!r}, None); "
    code += f"{o}()"
    return code


def _best_python_entry(project_dir: Path, pdata: dict | None) -> str | None:
    """Pick the most likely Python entry file inside ``project_dir``."""
    pyproject_text = ""
    try:
        pyproject_text = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
    except Exception:
        pyproject_text = ""
    if "[tool.mcp]" in pyproject_text and "server" in pyproject_text:
        return "server.py"

    common = ("main.py", "server.py", "app.py", "cli.py", "mcp_server.py", "__main__.py")
    for name in common:
        if (project_dir / name).exists():
            return name
    try:
        for f in sorted(project_dir.glob("*.py")):
            return f.name
    except Exception:
        pass
    return None


def _pick_local_entry(tmp_dir: Any) -> list[str] | None:
    """Heuristically pick the most likely MCP entry command from a clone."""
    import json
    from pathlib import Path as _P

    root = _P(tmp_dir)

    # ── Monorepo sub-project check ──
    if not (root / "package.json").exists() and not (root / "pyproject.toml").exists() and not (root / "go.mod").exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and "mcp" in child.name.lower():
                if (child / "pyproject.toml").exists() or (child / "package.json").exists():
                    sub_entry = _pick_local_entry(child)
                    if sub_entry:
                        if sub_entry[0] == "uv":
                            return sub_entry
                        res = []
                        for idx, token in enumerate(sub_entry):
                            if idx > 0 and not token.startswith("-") and (child / token).exists():
                                res.append(str((child / token).relative_to(root)))
                            else:
                                res.append(token)
                        return res

    # ── Node ──
    for rel in ("dist/index.js", "build/index.js", "src/index.js", "index.js"):
        if (root / rel).exists():
            return ["node", rel]

    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            bin_entry = pkg.get("bin")
            if isinstance(bin_entry, dict):
                entry = next(iter(bin_entry.values()))
            elif isinstance(bin_entry, str):
                entry = bin_entry
            else:
                entry = None
            if entry and (root / entry).exists():
                return ["node", str(entry)]
            main = pkg.get("main")
            if main and (root / main).exists():
                return ["node", str(main)]
        except Exception:
            pass

    # ── Go ──
    all_gomods = [root / "go.mod"] if (root / "go.mod").exists() else [
        f for f in sorted(root.rglob("go.mod"))
        if not any(part.startswith(".") or part in ("node_modules", "vendor", ".git") for part in f.relative_to(root).parts)
    ]
    if all_gomods:
        gomod = all_gomods[0]
        gdir = gomod.parent
        has_stdio_subcommand = False
        readme = ""
        try:
            readme = (root / "README.md").read_text(encoding="utf-8").lower()
        except Exception:
            pass
        if "stdio" in readme:
            has_stdio_subcommand = True
        else:
            for go_file in gdir.rglob("*.go"):
                try:
                    text = go_file.read_text(encoding="utf-8", errors="ignore").lower()
                    if "stdio" in text or "cobra" in text:
                        has_stdio_subcommand = True
                        break
                except Exception:
                    pass

        sub_args = ["stdio"] if has_stdio_subcommand else []

        cmd_dir = gdir / "cmd"
        if cmd_dir.is_dir():
            candidates = sorted(
                d for d in cmd_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            )
            for entry_dir in candidates:
                if (entry_dir / "main.go").exists():
                    rel_sub = entry_dir.relative_to(root)
                    return ["go", "run", f"./{rel_sub}"] + sub_args
        rel_gdir = gdir.relative_to(root)
        rel_str = f"./{rel_gdir}" if str(rel_gdir) != "." else "."
        return ["go", "run", rel_str] + sub_args

    # ── Python ──
    pyproject = root / "pyproject.toml"
    project_dir = root
    if not pyproject.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and (
                "__pycache__" not in child.parts
            ):
                if (child / "pyproject.toml").exists():
                    pyproject = child / "pyproject.toml"
                    project_dir = child
                    break
    pdata: dict | None = None
    if pyproject.exists():
        try:
            import tomllib

            pdata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            pdata = None

    if pdata:
        from vendor.services import mcp_client
        shutil_mod = getattr(mcp_client, "shutil", shutil)
        if shutil_mod.which("uv"):
            scripts = (
                (pdata.get("project") or {}).get("scripts")
                or (pdata.get("project") or {}).get("gui-scripts")
                or {}
            )
            if scripts:
                name = next(iter(scripts.keys()))
                return ["uv", "run", "--directory", str(project_dir), str(name)]
            entry = _best_python_entry(project_dir, pdata)
            if entry:
                return ["uv", "run", "--directory", str(project_dir), "python", entry]

    if pdata:
        scripts = (
            (pdata.get("project") or {}).get("scripts")
            or (pdata.get("project") or {}).get("gui-scripts")
            or {}
        )
        if scripts:
            entry = next(iter(scripts.values()))
            code = _python_console_entry_code(project_dir, entry)
            if code:
                return ["python", "-c", code]

    if pdata:
        tool_mcp = (pdata.get("tool") or {}).get("mcp", {}).get("servers", {})
        if tool_mcp:
            srv = next(iter(tool_mcp.values()), {})
            cmd = srv.get("command")
            if cmd:
                return [cmd] + list(srv.get("args") or [])[:2]

    for rel in ("server.py", "main.py", "mcp_server.py", "app.py"):
        if (root / rel).exists():
            return ["python", rel]

    for base in (root, root / "src"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name in (
                "__pycache__", ".git", "node_modules", ".venv", "venv",
            ):
                continue
            if (child / "__main__.py").exists():
                code = (
                    "import runpy, sys; "
                    f"sys.path.insert(0, {str(base)!r}); "
                    f"runpy.run_module({child.name!r}, run_name='__main__')"
                )
                return ["python", "-c", code]

    for target in ("server.py", "mcp_server.py", "main.py"):
        for hit in sorted(root.rglob(target)):
            rel_parts = hit.relative_to(root).parts
            if any(p in ("__pycache__", ".git", "node_modules", ".venv", "venv") for p in rel_parts):
                continue
            rel = str(hit.relative_to(root))
            if rel != target:
                return ["python", rel]

    return None


async def _fetch_repo_tarball(owner: str, repo: str, dest_dir: Any) -> None:
    """Download and extract a GitHub repo tarball."""
    import io
    import tarfile
    import tempfile

    last_status = 0
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        for branch in ("main", "master"):
            url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.tar.gz"
            resp = await client.get(url)
            if resp.status_code == 200:
                break
            last_status = resp.status_code
        else:
            raise ConnectionError(
                f"tarball download failed for {owner}/{repo} (HTTP {last_status})"
            )

    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
            tf.extractall(td, filter="data")
        extracted = next(Path(td).iterdir())
        shutil.copytree(extracted, dest_dir, dirs_exist_ok=True)


async def _prepare_local_repo_stdio(
    command: str, source_repo_url: str | None
) -> tuple[str, list[str], str | None]:
    """Resolves stdio command parameters."""
    parts = shlex.split(command)
    cwd = None

    git_url: str | None = None
    if "github.com" in command or command.startswith("git+"):
        git_url = command
    elif source_repo_url and (not parts or parts[0] not in _PACKAGE_RUNNER_COMMANDS):
        git_url = source_repo_url

    if git_url and ("github.com" in git_url or git_url.startswith("http")):
        try:
            import re
            import subprocess

            subpath = None
            subpath_match = re.search(r"/tree/[^/]+/(.+)$", git_url)
            if subpath_match:
                subpath = subpath_match.group(1).strip("/")

            match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$", git_url)
            if match:
                owner, repo = match.groups()
                tmp_dir = Path("/tmp/mcp_repos") / f"{owner}_{repo}"
                canonical_git_url = f"https://github.com/{owner}/{repo}"

                def _has_manifest() -> bool:
                    if not tmp_dir.is_dir():
                        return False
                    check_dir = (tmp_dir / subpath) if (subpath and (tmp_dir / subpath).is_dir()) else tmp_dir
                    if (check_dir / "package.json").exists() or (check_dir / "pyproject.toml").exists() or (check_dir / "go.mod").exists():
                        return True
                    try:
                        return any(
                            (child / "package.json").exists()
                            or (child / "pyproject.toml").exists()
                            or (child / "go.mod").exists()
                            for child in check_dir.iterdir()
                            if child.is_dir() and not child.name.startswith(".")
                        )
                    except OSError:
                        return False

                if tmp_dir.exists() and not _has_manifest():
                    logger.info("removing stale repo cache %s", tmp_dir)
                    shutil.rmtree(tmp_dir, ignore_errors=True)

                if not _has_manifest():
                    try:
                        subprocess.run(
                            ["git", "clone", "--depth", "1", canonical_git_url, str(tmp_dir)],
                            check=True,
                            capture_output=True,
                            timeout=_REPO_CLONE_TIMEOUT,
                        )
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as clone_exc:
                        logger.warning(
                            "git clone failed for %s (%s); falling back to tarball download",
                            canonical_git_url,
                            clone_exc,
                        )
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        await _fetch_repo_tarball(owner, repo, tmp_dir)

                target_dir = (tmp_dir / subpath) if (subpath and (tmp_dir / subpath).is_dir()) else tmp_dir

                if (target_dir / "package.json").exists():
                    subprocess.run(
                        ["npm", "install", "--no-audit", "--no-fund"],
                        cwd=target_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )
                    subprocess.run(
                        ["npm", "run", "build"],
                        cwd=target_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )

                if (target_dir / "go.mod").exists():
                    subprocess.run(
                        ["go", "mod", "download"],
                        cwd=target_dir, capture_output=True, timeout=_REPO_BUILD_TIMEOUT,
                    )

                cwd = str(target_dir)

                from vendor.services import mcp_client
                pick_fn = getattr(mcp_client, "_pick_local_entry", _pick_local_entry)
                found = pick_fn(target_dir)
                if found:
                    orig_extra = [
                        p for p in parts
                        if p not in ("go", "run", "node", "python", "uv", "npm", "npx", ".")
                        and not p.startswith("./")
                        and not any(p.endswith(ext) for ext in (".js", ".py", ".ts", ".go", ".mjs"))
                    ]
                    for extra in orig_extra:
                        if extra not in found:
                            found.append(extra)
                    parts = found
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed_to_prepare_local_repo %s: %s", git_url, exc)

    if not parts:
        raise ValueError(
            f"Invalid stdio command for {command!r}: unable to determine executable command or entry point."
        )

    return parts[0], parts[1:], cwd


def _sanitize_stdio_env(env: dict[str, str]) -> dict[str, str]:
    """Drop backend-virtualenv state that must not leak into spawned servers."""
    stray_keys = {"VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE"}
    cleaned = {k: v for k, v in env.items() if k not in stray_keys}
    path = cleaned.get("PATH")
    if path:
        kept = [p for p in path.split(os.pathsep) if p and ".venv" not in Path(p).parts]
        cleaned["PATH"] = os.pathsep.join(kept)
    return cleaned


async def _connect_stdio(
    command: str,
    credentials: dict[str, str] | None,
    source_repo_url: str | None = None,
    env_vars: dict[str, str] | None = None,
) -> dict:
    """Spawn a stdio MCP server process and run initialize + tools/list."""

    # Import _session_details lazily or from transport module
    from vendor.services.mcp_client.transport import _session_details

    env = _sanitize_stdio_env({**os.environ})
    if isinstance(env_vars, dict):
        env.update(
            {
                str(k).upper(): str(v)
                for k, v in env_vars.items()
                if isinstance(v, str) and v.strip() and v.strip().lower() != "null"
            }
        )
    if credentials:
        env.update({k.upper(): v for k, v in credentials.items()})
        if "GITHUB_TOKEN" in env and "GITHUB_PERSONAL_ACCESS_TOKEN" not in env:
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = env["GITHUB_TOKEN"]
        elif "GITHUB_PERSONAL_ACCESS_TOKEN" in env and "GITHUB_TOKEN" not in env:
            env["GITHUB_TOKEN"] = env["GITHUB_PERSONAL_ACCESS_TOKEN"]

    client_id = env.get("CLIENT_ID") or env.get("GOOGLE_CLIENT_ID") or env.get("GMAIL_CLIENT_ID") or env.get("OAUTH_CLIENT_ID")
    client_secret = env.get("CLIENT_SECRET") or env.get("GOOGLE_CLIENT_SECRET") or env.get("GMAIL_CLIENT_SECRET") or env.get("OAUTH_CLIENT_SECRET")
    refresh_token = env.get("REFRESH_TOKEN") or env.get("GOOGLE_REFRESH_TOKEN") or env.get("GMAIL_REFRESH_TOKEN")
    access_token = env.get("ACCESS_TOKEN") or env.get("GOOGLE_ACCESS_TOKEN") or env.get("GMAIL_ACCESS_TOKEN")

    if client_id:
        env.setdefault("CLIENT_ID", client_id)
        env.setdefault("GOOGLE_CLIENT_ID", client_id)
        env.setdefault("GMAIL_CLIENT_ID", client_id)
        env.setdefault("OAUTH_CLIENT_ID", client_id)
    if client_secret:
        env.setdefault("CLIENT_SECRET", client_secret)
        env.setdefault("GOOGLE_CLIENT_SECRET", client_secret)
        env.setdefault("GMAIL_CLIENT_SECRET", client_secret)
        env.setdefault("OAUTH_CLIENT_SECRET", client_secret)

    from vendor.services import mcp_client
    prep_fn = getattr(mcp_client, "_prepare_local_repo_stdio", _prepare_local_repo_stdio)
    cmd_binary, cmd_args, cwd = await prep_fn(command, source_repo_url)

    if client_id or client_secret or refresh_token or access_token:
        import json

        oauth_json_data = {
            "installed": {
                "client_id": client_id or "",
                "client_secret": client_secret or "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost:3000/oauth2callback"],
            },
            "web": {
                "client_id": client_id or "",
                "client_secret": client_secret or "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost:3000/oauth2callback"],
            },
        }

        cwd_path = Path(cwd) if cwd else Path.cwd()
        cwd_oauth_file = cwd_path / "gcp-oauth.keys.json"
        cwd_creds_file = cwd_path / "credentials.json"

        if client_id and client_secret and not cwd_oauth_file.exists():
            cwd_oauth_file.write_text(json.dumps(oauth_json_data, indent=2), encoding="utf-8")

        if (refresh_token or access_token) and not cwd_creds_file.exists():
            creds_data = {
                "access_token": access_token or "placeholder_token",
                "refresh_token": refresh_token or "",
                "token_type": "Bearer",
            }
            cwd_creds_file.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")

        home = Path.home()
        for conf_dir in (home / ".gmail-mcp", home / ".config" / "google-drive-mcp", home / ".mcp"):
            conf_dir.mkdir(parents=True, exist_ok=True)
            o_file = conf_dir / "gcp-oauth.keys.json"
            c_file = conf_dir / "credentials.json"
            if client_id and client_secret and not o_file.exists():
                o_file.write_text(json.dumps(oauth_json_data, indent=2), encoding="utf-8")
            if (refresh_token or access_token) and not c_file.exists():
                creds_data = {
                    "access_token": access_token or "placeholder_token",
                    "refresh_token": refresh_token or "",
                    "token_type": "Bearer",
                }
                c_file.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")

        target_oauth_path = str(cwd_oauth_file if cwd_oauth_file.exists() else home / ".gmail-mcp" / "gcp-oauth.keys.json")
        target_creds_path = str(cwd_creds_file if cwd_creds_file.exists() else home / ".gmail-mcp" / "credentials.json")

        env.setdefault("GMAIL_OAUTH_PATH", target_oauth_path)
        env.setdefault("GOOGLE_DRIVE_OAUTH_CREDENTIALS", target_oauth_path)
        env.setdefault("OAUTH_KEYS_PATH", target_oauth_path)
        env.setdefault("GCP_OAUTH_KEYS_PATH", target_oauth_path)
        env.setdefault("GMAIL_CREDENTIALS_PATH", target_creds_path)
        env.setdefault("CREDENTIALS_PATH", target_creds_path)

    logger.info(
        "starting_mcp_stdio",
        command=cmd_binary,
        args=cmd_args,
        cwd=cwd,
        env_keys=list(env.keys()),
    )

    params = StdioServerParameters(command=cmd_binary, args=cmd_args, env=env, cwd=cwd)
    from vendor.services import mcp_client
    stdio_fn = getattr(mcp_client, "stdio_client", stdio_client)
    session_details_fn = getattr(mcp_client, "_session_details", _session_details)
    async with stdio_fn(params) as (read_stream, write_stream):
        details = await session_details_fn(read_stream, write_stream)
    logger.info("stdio connected to %s — discovered %d tool(s)", command, len(details["tools"]))
    return {
        "transport": "stdio",
        "bound_tools": [t["name"] for t in details["tools"]],
        "tools": details["tools"],
        "server_info": details["server_info"],
        "protocol_version": details["protocol_version"],
        "auth_type": "env" if credentials else "none",
    }
