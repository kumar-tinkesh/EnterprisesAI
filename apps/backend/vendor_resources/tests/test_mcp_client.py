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


def test_python_pyproject_console_script(tmp_path):
    """pyproject [project.scripts] should map to python -m."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nscripts = { "weather-mcp" = "mcp_weather:main" }\n'
    )
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["python", "-m", "mcp_weather"]


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
    """A __main__.py package should map to python -m."""
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__main__.py").write_text("")
    cmd = _pick_local_entry(tmp_path)
    assert cmd == ["python", "-m", "src.pkg"]


def test_nothing_found(tmp_path):
    """Empty dir → None."""
    assert _pick_local_entry(tmp_path) is None