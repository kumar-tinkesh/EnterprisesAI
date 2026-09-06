"""Unit tests for the MCP client local-entry resolution helper."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from vendor.services.mcp_client import _pick_local_entry
from vendor.services.repo_analyzer import (
    _best_python_entry,
    _scan_local_dir,
)


def test_node_dist_build(tmp_path):
    """Node build output should be preferred."""
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.js").write_text("")
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["node", "dist/index.js"]


def test_node_package_bin(tmp_path):
    """package.json bin entry should be used when present."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "srv.js").write_text("")
    (tmp_path / "package.json").write_text(
        '{"name": "srv", "bin": {"srv": "bin/srv.js"}}'
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["node", "bin/srv.js"]


def test_node_package_main(tmp_path):
    """package.json main should be used as the entry."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("")
    (tmp_path / "package.json").write_text(
        '{"name": "srv", "main": "src/main.js"}'
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["node", "src/main.js"]


def test_python_root_server(tmp_path):
    """Root server.py should be chosen for Python projects."""
    (tmp_path / "server.py").write_text("")
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["python", "server.py"]


def test_python_pyproject_console_script(tmp_path, monkeypatch):
    """[project.scripts] should run the exact module:func without uv present."""
    (tmp_path / "mcp_weather").mkdir()
    (tmp_path / "mcp_weather" / "__init__.py").write_text("")
    (tmp_path / "mcp_weather" / "weather.py").write_text("mcp = object()\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nscripts = { "mcp-weather" = "mcp_weather.weather:mcp.run" }\n'
    )
    monkeypatch.setattr(
        "vendor.services.mcp_client.shutil.which", lambda _: None
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd[:2] == ["python", "-c"]
    assert "mcp_weather.weather" in cmd[2]


def test_scan_local_dir_drills_into_subdir(tmp_path):
    """A repo whose server lives in a nested dir is scanned from that dir."""
    base = tmp_path
    sub = base / "whatsapp-mcp-server"
    sub.mkdir()
    (sub / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (sub / "main.py").write_text("print('hi')\n")
    (base / "README.md").write_text("top level only\n")
    scanned = asyncio.run(_scan_local_dir(base))
    assert scanned.get("_server_subdir") == "whatsapp-mcp-server"
    assert "pyproject.toml" in scanned
    assert "main.py" in scanned.get("python_files", [])


def test_best_python_entry_picks_real_file():
    """_best_python_entry prefers an existing main.py over the server.py default."""
    assert _best_python_entry("", "", ["main.py", "whatsapp.py"]) == "main.py"
    assert _best_python_entry("[tool.mcp]\nserver = x", "", ["main.py"]) == "server.py"
    assert _best_python_entry("", "requests", []) == "mcp_server.py"
    assert _best_python_entry("", "", []) == "server.py"


def test_python_pyproject_console_script_via_uv(tmp_path, monkeypatch):
    """When uv is available, a console script runs via uv (auto-installs deps)."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nscripts = { "mcp-weather" = "mcp_weather.weather:mcp.run" }\n'
    )
    monkeypatch.setattr(
        "vendor.services.mcp_client.shutil.which",
        lambda name: "/usr/local/bin/uv" if name == "uv" else None,
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["uv", "run", "--directory", str(tmp_path), "mcp-weather"]


def test_python_pyproject_tool_mcp(tmp_path):
    """pyproject [tool.mcp.servers] command should be honored."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mcp.servers.weather]\ncommand = "uv"\nargs = ["run", "weather.py"]\n'
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd[:1] == ["uv"]


def test_python_recursive_server(tmp_path):
    """A nested server.py under src should be found."""
    (tmp_path / "src" / "deep").mkdir(parents=True)
    (tmp_path / "src" / "deep" / "server.py").write_text("")
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["python", "src/deep/server.py"]


def test_python_main_module(tmp_path):
    """A __main__.py package should run via runpy (flat or src/ layout)."""
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__main__.py").write_text("")
    cmd = _pick_local_entry(tmp_path)
    assert cmd[:2] == ["python", "-c"]
    assert "runpy.run_module('pkg'" in cmd[2] or "runpy.run_module(\"pkg\"" in cmd[2]


def test_python_nested_subdir_entry(tmp_path):
    """Entry file in a nested subdirectory (e.g. whatsapp-mcp-server/) is found
    and runs via uv run --directory so its own deps install in isolation and
    the process CWD lands in the project dir."""
    (tmp_path / "whatsapp-mcp-server").mkdir()
    (tmp_path / "whatsapp-mcp-server" / "main.py").write_text("")
    (tmp_path / "whatsapp-mcp-server" / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    cmd = _pick_local_entry(tmp_path)
    assert cmd[0] == "uv"
    assert cmd[1] == "run"
    assert cmd[2] == "--directory"
    assert cmd[3].endswith("whatsapp-mcp-server")
    assert cmd[4] == "python"
    assert cmd[5] == "main.py"


def test_python_nested_subdir_no_pyproject(tmp_path, monkeypatch):
    """Without a pyproject.toml the nested entry falls back to system python."""
    (tmp_path / "whatsapp-mcp-server").mkdir()
    (tmp_path / "whatsapp-mcp-server" / "main.py").write_text("")
    monkeypatch.setattr(
        "vendor.services.mcp_client.shutil.which", lambda _: None
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["python", "whatsapp-mcp-server/main.py"]



def test_python_console_entry_code(tmp_path, monkeypatch):
    """python -c snippet imports the exact module object and calls it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pkg").mkdir()
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("")
    (tmp_path / "src" / "pkg" / "app.py").write_text("srv = None\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nscripts = { "app" = "pkg.app:srv.run" }\n'
    )
    monkeypatch.setattr(
        "vendor.services.mcp_client.shutil.which", lambda _: None
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd[:2] == ["python", "-c"]
    assert "importlib.import_module('pkg.app')" in cmd[2]
    assert "getattr(_o, 'srv'" in cmd[2]
    assert "getattr(_o, 'run'" in cmd[2]


def test_nothing_found(tmp_path):
    """Empty dir → None."""
    assert _pick_local_entry(tmp_path) is None


def test_sanitize_stdio_env_drops_backend_venv_state():
    """Spawned servers must not inherit the backend's venv state: uv would
    warn (VIRTUAL_ENV mismatch) and stray PYTHON* vars could shadow the
    server's own dependencies."""
    from vendor.services.mcp_client import _sanitize_stdio_env

    env = {
        "VIRTUAL_ENV": "/app/.venv",
        "PYTHONPATH": "/app/.venv/lib/site-packages",
        "PYTHONHOME": "/usr",
        "PATH": "/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "KEEP_ME": "yes",
    }
    cleaned = _sanitize_stdio_env(env)
    assert "VIRTUAL_ENV" not in cleaned
    assert "PYTHONPATH" not in cleaned
    assert "PYTHONHOME" not in cleaned
    assert cleaned["KEEP_ME"] == "yes"
    assert ".venv" not in cleaned["PATH"]
    assert "/usr/local/bin:/usr/bin:/bin" == cleaned["PATH"]


# ── _prepare_local_repo_stdio: stale cache handling ────────────────────────


@pytest.mark.asyncio
async def test_prepare_reuses_cached_repo_with_nested_manifest(monkeypatch):
    """A cached checkout whose manifest lives in a subdirectory (e.g.
    lharries/whatsapp-mcp → whatsapp-mcp-server/) must be REUSED — the old
    code only recognized root manifests, so git clone re-ran and exited 128
    ('destination path already exists')."""
    import shutil as _shutil
    import subprocess

    import vendor.services.mcp_client as mc

    cache = Path("/tmp/mcp_repos/testowner_testrepo-nested")
    _shutil.rmtree(cache, ignore_errors=True)
    sub = cache / "whatsapp-mcp-server"
    sub.mkdir(parents=True)
    (sub / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (sub / "main.py").write_text("")

    clone_calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        clone_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("subprocess.run", _fake_run)
    async def _no_tarball(owner, repo, dest):
        raise AssertionError("tarball fallback must not run for a valid cache")

    monkeypatch.setattr(mc, "_fetch_repo_tarball", _no_tarball)

    cmd_bin, cmd_args, cwd = await mc._prepare_local_repo_stdio(
        "main.py", "https://github.com/testowner/testrepo-nested"
    )
    _shutil.rmtree(cache, ignore_errors=True)
    assert clone_calls == [], f"unexpected clone calls: {clone_calls}"
    assert cwd == str(cache)
    assert cmd_bin == "uv"
    assert cmd_args[:3] == ["run", "--directory", str(sub)]


@pytest.mark.asyncio
async def test_prepare_removes_stale_cache_before_clone(monkeypatch):
    """A leftover directory with NO manifest anywhere (root or subdir) is
    stale — it must be rmtree'd so `git clone` into the same path does not
    exit 128, then the clone proceeds."""
    import shutil as _shutil
    import subprocess

    import vendor.services.mcp_client as mc

    cache = Path("/tmp/mcp_repos/testowner_testrepo-stale")
    _shutil.rmtree(cache, ignore_errors=True)
    (cache / "leftover-junk").mkdir(parents=True)
    (cache / "leftover-junk" / "readme.md").write_text("junk")

    def _fake_run(cmd, **kwargs):
        # Emulate a real clone: create the destination, land a project the
        # entry-picker resolves.
        if cmd[:2] == ["git", "clone"]:
            dest = Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "package.json").write_text('{"main": "index.js"}')
            (dest / "dist").mkdir()
            (dest / "dist" / "index.js").write_text("// built output")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("subprocess.run", _fake_run)
    async def _no_tarball(owner, repo, dest):
        raise AssertionError("tarball fallback must not run when clone succeeds")

    monkeypatch.setattr(mc, "_fetch_repo_tarball", _no_tarball)

    cmd_bin, cmd_args, cwd = await mc._prepare_local_repo_stdio(
        "node index.js", "https://github.com/testowner/testrepo-stale"
    )
    _shutil.rmtree(cache, ignore_errors=True)
    assert cwd == str(cache)
    assert not (cache / "leftover-junk").exists() if cache.exists() else True
    # The entry-picker (not the raw command) determines what runs.
    assert cmd_bin == "node"
    assert cmd_args == ["dist/index.js"]


@pytest.mark.asyncio
async def test_connect_stdio_without_credentials(monkeypatch):
    """Connecting a stdio server with no credentials must not raise UnboundLocalError for client_id."""
    from contextlib import asynccontextmanager

    import vendor.services.mcp_client as mc

    async def _mock_prepare(command, repo_url):
        return "python", ["main.py"], "/tmp"

    @asynccontextmanager
    async def _mock_stdio_client(params):
        yield ("read", "write")

    async def _mock_session_details(read_stream, write_stream):
        return {
            "tools": [],
            "server_info": {"name": "whatsapp-mcp", "version": "1.0"},
            "protocol_version": "2024-11-05",
        }

    monkeypatch.setattr(mc, "_prepare_local_repo_stdio", _mock_prepare)
    monkeypatch.setattr(mc, "stdio_client", _mock_stdio_client)
    monkeypatch.setattr(mc, "_session_details", _mock_session_details)

    config = {
        "transport": "stdio",
        "command": "python main.py",
        "source_repo_url": "https://github.com/lharries/whatsapp-mcp",
        "credentials": None,
        "env": {},
    }
    client = mc.MCPClient()
    result = await client.connect(config)
    assert result["transport"] == "stdio"