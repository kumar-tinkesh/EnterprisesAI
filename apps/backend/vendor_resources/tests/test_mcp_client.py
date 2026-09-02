"""Unit tests for the MCP client local-entry resolution helper."""
from __future__ import annotations

from vendor_resources.services.mcp_client import _pick_local_entry


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
        "vendor_resources.services.mcp_client.shutil.which", lambda _: None
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd[:2] == ["python", "-c"]
    assert "mcp_weather.weather" in cmd[2]
    assert "run" in cmd[2]


def test_python_pyproject_console_script_via_uv(tmp_path, monkeypatch):
    """When uv is available, a console script runs via uv (auto-installs deps)."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nscripts = { "mcp-weather" = "mcp_weather.weather:mcp.run" }\n'
    )
    monkeypatch.setattr(
        "vendor_resources.services.mcp_client.shutil.which",
        lambda name: "/usr/local/bin/uv" if name == "uv" else None,
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["uv", "run", "--project", str(tmp_path), "mcp-weather"]


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
        "vendor_resources.services.mcp_client.shutil.which", lambda _: None
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd[:2] == ["python", "-c"]
    assert "importlib.import_module('pkg.app')" in cmd[2]
    assert "getattr(_o, 'srv'" in cmd[2]
    assert "getattr(_o, 'run'" in cmd[2]


def test_nothing_found(tmp_path):
    """Empty dir → None."""
    assert _pick_local_entry(tmp_path) is None