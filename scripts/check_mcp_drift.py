#!/usr/bin/env python3
"""MCP tool-surface drift checker.

Catches silent drift between the MCP servers' *real* tool surface (as reported
live by ``hermes mcp test <name>``) and the documented/expected one stored in
``scripts/mcp_baseline.json``.

For every server listed in the baseline it runs ``hermes mcp test <name>`` as a
subprocess with a generous timeout, parses the ``✓ Connected (NNNNms)`` and
``✓ Tools discovered: N`` lines from stdout, and compares N against the
baseline's expected count.

    Sunucu            beklenen   bulunan   durum
    bridge            8          8         ok
    context7          2          -         devre dışı

Status values:
    ok            tool count matches the baseline
    DRIFT         server reachable but the tool count changed
    ERİŞİLEMEDİ   server could not be tested (error / timeout / bad entry file)
    devre dışı    server config entry is disabled (not a failure)

Exit code is 1 when any server drifts or is unreachable, 0 otherwise.

Flags:
    --update            rewrite the baseline from the current live counts
    --json              machine-readable JSON output instead of the table
    --only a,b,c        restrict the check to the named servers
    --timeout SECONDS   per-server ``hermes mcp test`` timeout (default 180)
    --baseline PATH     alternate baseline file
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = SCRIPT_DIR / "mcp_baseline.json"

HERMES = shutil.which("hermes") or "hermes"
DEFAULT_TIMEOUT = 180.0

STATUS_OK = "ok"
STATUS_DRIFT = "DRIFT"
STATUS_UNREACHABLE = "ERİŞİLEMEDİ"
STATUS_DISABLED = "devre dışı"

# Order used when rendering the summary table (unknown servers sort last).
_KNOWN_ORDER = [
    "bridge",
    "chatcut",
    "context7",
    "filesystem",
    "github",
    "hyperframes-local",
    "makale",
    "notion",
    "shamela",
    "yargi",
    "zotero",
]

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_RE_CONNECTED = re.compile(r"Connected\s*\((\d+)\s*ms\)", re.IGNORECASE)
_RE_TOOLS = re.compile(r"Tools discovered:\s*(\d+)", re.IGNORECASE)
_RE_DISABLED = re.compile(r"\bdisabled\b", re.IGNORECASE)
_RE_LIST_ROW = re.compile(r"^(\S+)\s+.*?(enabled|disabled)\s*$", re.IGNORECASE)


def parse_test_output(text: str) -> dict:
    """Parse the stdout/stderr of ``hermes mcp test <name>``.

    Returns a dict with:
        connected : bool   -- a ``✓ Connected (NNNNms)`` line was seen
        count     : int|None -- value from ``✓ Tools discovered: N``
        ms        : int|None -- connection time in milliseconds
        disabled  : bool   -- the output mentions the server is disabled
    """
    text = text or ""
    m = _RE_CONNECTED.search(text)
    connected = m is not None
    ms = int(m.group(1)) if m else None

    m2 = _RE_TOOLS.search(text)
    count = int(m2.group(1)) if m2 else None

    disabled = _RE_DISABLED.search(text) is not None

    return {"connected": connected, "count": count, "ms": ms, "disabled": disabled}


def parse_list_output(text: str) -> dict:
    """Parse ``hermes mcp list`` into ``{name: enabled_bool}``.

    Only data rows are captured: the header (Name/Transport/Tools/Status) and
    the box-drawing separator do not end in ``enabled`` / ``disabled`` so they
    are ignored.
    """
    out: dict[str, bool] = {}
    for line in (text or "").splitlines():
        m = _RE_LIST_ROW.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).lower() == "enabled"
    return out


def classify(expected, test_result: dict, is_disabled: bool) -> str:
    """Decide the drift status for one server."""
    if is_disabled:
        return STATUS_DISABLED
    if not test_result.get("connected") or test_result.get("count") is None:
        return STATUS_UNREACHABLE
    if expected is not None and test_result.get("count") != expected:
        return STATUS_DRIFT
    return STATUS_OK


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def load_baseline(path: Path) -> tuple[dict, dict]:
    """Return ``(raw_payload, {name: expected_count})``.

    Accepts either ``{"servers": {...}}`` (canonical) or a flat
    ``{name: count}`` map for convenience.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = raw.get("servers", raw) if isinstance(raw, dict) else {}
    expected: dict[str, object] = {}
    for key, value in servers.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            expected[key] = value.get("expected_tools")
        else:
            expected[key] = value
    return raw, expected


def save_baseline(path: Path, counts: dict, hermes_version: str | None = None) -> None:
    payload = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": (
                "Expected MCP tool counts measured live via 'hermes mcp test'. "
                "Regenerate with: python scripts/check_mcp_drift.py --update"
            ),
            "hermes_version": hermes_version,
        },
        "servers": dict(counts),
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _subprocess_env() -> dict:
    """Environment for the ``hermes`` subprocesses.

    ``UV_NO_SYNC=1`` is set by default: the ``uv run --project`` based servers
    (bridge/makale/yargi) are spawned by ``hermes mcp test``, and if a stale
    server process still holds ``.venv/Scripts/<name>.exe`` a plain ``uv run``
    would try to re-sync the venv, fail to replace the locked exe and report the
    server as unreachable. Skipping the sync keeps the check side-effect free
    and reproducible. Respect any value the caller already set.
    """
    env = dict(os.environ)
    env.setdefault("UV_NO_SYNC", "1")
    return env


def hermes_version() -> str | None:
    try:
        proc = subprocess.run(
            [HERMES, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=_subprocess_env(),
        )
        first = (proc.stdout or proc.stderr or "").strip().splitlines()
        return first[0] if first else None
    except Exception:
        return None


def get_disabled_map(timeout: float) -> dict[str, bool]:
    """Return ``{name: enabled_bool}`` from ``hermes mcp list``.

    On any failure returns ``{}`` so the caller treats every server as enabled
    and relies on the test output instead.
    """
    try:
        proc = subprocess.run(
            [HERMES, "mcp", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(timeout, 60),
            env=_subprocess_env(),
        )
    except Exception:
        return {}
    return parse_list_output(proc.stdout or "")


def run_mcp_test(name: str, timeout: float) -> dict:
    """Run ``hermes mcp test <name>`` and return parsed result + raw fields."""
    try:
        proc = subprocess.run(
            [HERMES, "mcp", "test", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return {
            "connected": False,
            "count": None,
            "ms": None,
            "disabled": False,
            "rc": None,
            "error": f"zaman aşımı ({timeout:.0f}s)",
            "stdout": "",
            "stderr": "",
        }
    except FileNotFoundError as exc:  # hermes binary not on PATH
        return {
            "connected": False,
            "count": None,
            "ms": None,
            "disabled": False,
            "rc": None,
            "error": f"hermes bulunamadı: {exc}",
            "stdout": "",
            "stderr": "",
        }

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    result = parse_test_output(combined)
    result["rc"] = proc.returncode
    result["stdout"] = proc.stdout or ""
    result["stderr"] = proc.stderr or ""
    if not result["connected"]:
        # Pull a single human-readable error line out of the output.
        err_line = ""
        for line in combined.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("[") and len(stripped) > 2:
                err_line = stripped
                break
        result["error"] = err_line or "bağlantı kurulamadı"
    else:
        result["error"] = ""
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _sort_key(name: str) -> tuple:
    try:
        return (0, _KNOWN_ORDER.index(name))
    except ValueError:
        return (1, name)


def render_table(rows: list[dict]) -> str:
    headers = ("Sunucu", "beklenen", "bulunan", "durum")
    data = [(r["server"], str(r["expected"]), str(r["found"]), r["status"]) for r in rows]
    widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cols):
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)).rstrip()

    lines = [fmt(headers), fmt(["-" * w for w in widths])]
    for row in data:
        lines.append(fmt(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_update(args) -> int:
    baseline_path = Path(args.baseline)
    if baseline_path.exists():
        _, expected = load_baseline(baseline_path)
    else:
        expected = {}

    # Discover the live server set too, so newly added servers land in the file.
    listed = get_disabled_map(args.timeout)
    names = list(dict.fromkeys(list(expected.keys()) + list(listed.keys())))

    counts: dict[str, int] = {}
    for name in names:
        res = run_mcp_test(name, args.timeout)
        if res["count"] is not None:
            counts[name] = res["count"]
            flag = "devre dışı" if not listed.get(name, True) else ""
            print(f"  {name}: {res['count']} {flag}".rstrip(), file=sys.stderr)
        elif name in expected and expected[name] is not None:
            counts[name] = expected[name]  # keep previous value
            print(
                f"  {name}: ölçülemedi, önceki değer korundu ({expected[name]})",
                file=sys.stderr,
            )
        else:
            print(f"  {name}: ölçülemedi, atlandı", file=sys.stderr)

    # Preserve sort order: known servers first, then alphabetical.
    counts = {k: counts[k] for k in sorted(counts, key=_sort_key)}

    save_baseline(baseline_path, counts, hermes_version())
    print(f"Baseline yazıldı: {baseline_path} ({len(counts)} sunucu)", file=sys.stderr)
    return 0


def cmd_check(args) -> int:
    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(f"HATA: baseline bulunamadı: {baseline_path}", file=sys.stderr)
        return 2
    _, expected = load_baseline(baseline_path)

    names = list(expected.keys())
    names.sort(key=_sort_key)

    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        names = [n for n in names if n in wanted]

    disabled_map = get_disabled_map(args.timeout)

    rows: list[dict] = []
    for name in names:
        exp = expected.get(name)
        is_disabled = disabled_map.get(name) is False
        if is_disabled:
            res = {"connected": False, "count": None, "ms": None, "rc": None, "error": ""}
        else:
            res = run_mcp_test(name, args.timeout)
        status = classify(exp, res, is_disabled)
        found = res["count"] if res["count"] is not None else "-"
        rows.append(
            {
                "server": name,
                "expected": exp if exp is not None else "-",
                "found": found,
                "status": status,
                "ms": res.get("ms"),
                "rc": res.get("rc"),
                "error": res.get("error", ""),
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(render_table(rows))

    failing = [r for r in rows if r["status"] in (STATUS_DRIFT, STATUS_UNREACHABLE)]
    return 1 if failing else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MCP tool-surface drift checker (hermes mcp test vs baseline)."
    )
    p.add_argument("--update", action="store_true", help="baseline'ı canlı sayımlarla yenile")
    p.add_argument("--json", action="store_true", help="makine okunur JSON çıktı")
    p.add_argument("--only", metavar="a,b,c", help="yalnızca bu sunucuları denetle")
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"sunucu başına 'hermes mcp test' zaman aşımı (varsayılan {DEFAULT_TIMEOUT:.0f}s)",
    )
    p.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="baseline dosyası")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.update:
        return cmd_update(args)
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
