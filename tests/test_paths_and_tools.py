import os
from pathlib import Path

import pytest

from bridge_mcp import _path_env, _existing_path_env

EXPECTED_TOOLS = {
    "bridge_health",
    "citation_export",
    "citation_search",
    "improvement_list",
    "improvement_log",
    "improvement_resolve",
    "isnad_kunye",
    "makale_durum",
    "shamela_makale_ata",
    "yargi_makale_cek",
    "yargi_zotero_kaydet",
}


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
    assert _existing_path_env("BRIDGE_TEST_REAL", tmp_path / "other") == str(real)


def test_server_registers_expected_tools():
    pytest.importorskip("mcp")
    from bridge_mcp.server import mcp
    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None and hasattr(manager, "list_tools"):
        # FastMCP sürümüne göre Tool nesnesi ya da isim döner.
        names = {getattr(tool, "name", tool) for tool in manager.list_tools()}
    else:  # çok eski/çok yeni FastMCP
        names = {t for t in dir(mcp) if not t.startswith("_")}
    missing = EXPECTED_TOOLS - set(names)
    assert not missing, f"beklenen tool eksik: {sorted(missing)}"


def test_server_registers_prompts():
    pytest.importorskip("mcp")
    from bridge_mcp.server import mcp
    manager = getattr(mcp, "_prompt_manager", None)
    if manager is None or not hasattr(manager, "list_prompts"):
        pytest.skip("prompt manager API'si bu mcp sürümünde farklı")
    names = {getattr(p, "name", p) for p in manager.list_prompts()}
    assert {"isnad_kunye_akisi", "yargi_makale_akisi"} <= names
