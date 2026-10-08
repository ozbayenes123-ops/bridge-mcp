import os
from pathlib import Path

from bridge_mcp import _path_env, _existing_path_env


def test_path_env_default(monkeypatch, tmp_path):
    monkeypatch.delenv("BRIDGE_TEST_UNSET_VAR", raising=False)
    assert _path_env("BRIDGE_TEST_UNSET_VAR", tmp_path / "vars") == str(tmp_path / "vars")


def test_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_TEST_VAR", str(tmp_path / "custom"))
    assert _path_env("BRIDGE_TEST_VAR", tmp_path / "vars") == str(tmp_path / "custom")


def test_existing_path_env_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("BRIDGE_TEST_MISSING", raising=False)
    assert _existing_path_env("BRIDGE_TEST_MISSING", tmp_path / "nope") is None


def test_existing_path_env_returns_existing(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setenv("BRIDGE_TEST_REAL", str(real))
    assert _existing_path_env("BRIDGE_TEST_REAL", tmp_path / "other") == real


def test_server_registers_expected_tools():
    from bridge_mcp.server import mcp
    tools = getattr(mcp, "_tool_manager", None)
    if tools is not None:
        names = set(tools.list_tools())
    else:  # FastMCP surum farkliliklari
        names = {t for t in dir(mcp) if not t.startswith("_")}
    for expected in ("bridge_health", "citation_search", "isnad_kunye"):
        assert expected in names, f"beklenen tool eksik: {expected}"
