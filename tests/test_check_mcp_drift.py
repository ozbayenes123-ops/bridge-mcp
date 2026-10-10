"""Unit tests for the drift-checker output parser (scripts/check_mcp_drift.py).

No hermes call and no network: every case feeds a hard-coded sample string to
the pure parser / classifier functions.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_mcp_drift as drift  # noqa: E402


# ---------------------------------------------------------------------------
# Hard-coded sample strings
# ---------------------------------------------------------------------------

SAMPLE_NORMAL = """
  Testing 'bridge'...
  Transport: stdio \u2192 uv
  Auth: none
  \u2713 Connected (8830ms)
  \u2713 Tools discovered: 14

    citation_search   Zotero'da ara...
    bridge_health     Bağlı bileşenlerin durumunu bildirir...
"""

# Server entry file missing / bad config: error line, no Connected, rc != 0.
SAMPLE_UNREACHABLE = (
    "\u2717 Server '__nope_xyz__' not found in config.\n"
    "  Available: bridge, chatcut, context7\n"
)

SAMPLE_UNREACHABLE_TRACEBACK = (
    "Traceback (most recent call last):\n"
    "  File \"server.py\", line 1, in <module>\n"
    "FileNotFoundError: [Errno 2] No such file or directory: 'main.js'\n"
)

# `hermes mcp list` output showing one enabled and one disabled server.
SAMPLE_LIST = """
  MCP Servers:

  Name             Transport                      Tools        Status
  \u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500  \u2500\u2500\u2500\u2500
  bridge           uv run --project               all          \u2713 enabled
  context7         https://mcp.context7.com/mcp   all          \u2717 disabled
  zotero           C:/Users/x/.local/bin/zotero   all          \u2713 enabled
"""

# Hypothetical test output that explicitly reports a disabled server.
SAMPLE_TEST_DISABLED = (
    "Testing 'context7'...\n"
    "  \u2717 disabled in config\n"
)


# ---------------------------------------------------------------------------
# Normal output
# ---------------------------------------------------------------------------


def test_parse_normal_connected():
    res = drift.parse_test_output(SAMPLE_NORMAL)
    assert res["connected"] is True
    assert res["count"] == 14
    assert res["ms"] == 8830
    assert res["disabled"] is False


def test_classify_normal_is_ok():
    res = drift.parse_test_output(SAMPLE_NORMAL)
    assert drift.classify(14, res, is_disabled=False) == drift.STATUS_OK


# ---------------------------------------------------------------------------
# Changed count -> DRIFT
# ---------------------------------------------------------------------------


def test_classify_changed_count_is_drift():
    res = drift.parse_test_output(SAMPLE_NORMAL)  # count == 14
    assert drift.classify(15, res, is_disabled=False) == drift.STATUS_DRIFT
    assert drift.classify(8, res, is_disabled=False) == drift.STATUS_DRIFT


def test_classify_missing_expected_still_ok():
    res = drift.parse_test_output(SAMPLE_NORMAL)
    assert drift.classify(None, res, is_disabled=False) == drift.STATUS_OK


# ---------------------------------------------------------------------------
# Unreachable / error output
# ---------------------------------------------------------------------------


def test_parse_unreachable_not_found():
    res = drift.parse_test_output(SAMPLE_UNREACHABLE)
    assert res["connected"] is False
    assert res["count"] is None
    assert drift.classify(14, res, is_disabled=False) == drift.STATUS_UNREACHABLE


def test_parse_unreachable_traceback():
    res = drift.parse_test_output(SAMPLE_UNREACHABLE_TRACEBACK)
    assert res["connected"] is False
    assert res["count"] is None
    assert drift.classify(14, res, is_disabled=False) == drift.STATUS_UNREACHABLE


def test_classify_empty_output_is_unreachable():
    res = drift.parse_test_output("")
    assert res["connected"] is False
    assert drift.classify(5, res, is_disabled=False) == drift.STATUS_UNREACHABLE


# ---------------------------------------------------------------------------
# Disabled output
# ---------------------------------------------------------------------------


def test_parse_list_output_flags_disabled():
    mapping = drift.parse_list_output(SAMPLE_LIST)
    assert mapping == {"bridge": True, "context7": False, "zotero": True}


def test_classify_disabled_is_not_failure():
    res = drift.parse_test_output(SAMPLE_LIST)
    assert drift.classify(2, res, is_disabled=True) == drift.STATUS_DISABLED
    # ...even when the live count would otherwise look like drift:
    assert drift.classify(99, res, is_disabled=True) == drift.STATUS_DISABLED


def test_parse_test_output_detects_disabled_marker():
    res = drift.parse_test_output(SAMPLE_TEST_DISABLED)
    assert res["disabled"] is True
    assert res["connected"] is False


# ---------------------------------------------------------------------------
# Table / status constant sanity
# ---------------------------------------------------------------------------


def test_render_table_contains_status():
    rows = [
        {"server": "bridge", "expected": 8, "found": 8, "status": drift.STATUS_OK},
        {"server": "context7", "expected": 2, "found": "-", "status": drift.STATUS_DISABLED},
    ]
    table = drift.render_table(rows)
    assert "Sunucu" in table and "beklenen" in table and "durum" in table
    assert "bridge" in table and "context7" in table
    assert drift.STATUS_DISABLED in table


def test_status_constants():
    assert drift.STATUS_OK == "ok"
    assert drift.STATUS_DRIFT == "DRIFT"
    assert drift.STATUS_UNREACHABLE == "ERİŞİLEMEDİ"
    assert drift.STATUS_DISABLED == "devre dışı"
