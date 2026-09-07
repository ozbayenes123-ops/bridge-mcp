"""isnad_word.py kanonik betiğini subprocess ile çağıran sarmalayıcı.

- prepare: Word gerekmez; üstveri stdin'den verilir, 3 form JSON olarak döner.
- export: atıf günlüğünden (JSONL) RIS/CSL-JSON üretir.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__

ISNAD_SCRIPT = Path(
    os.environ.get(
        "ISNAD_WORD_SCRIPT",
        r"C:\Users\ozbayenes123-ops\.commandcode\skills\isnad-word\scripts\isnad_word.py",
    )
)


class IsnadError(RuntimeError):
    pass


def _run(argv: list[str], stdin_text: str | None = None) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(ISNAD_SCRIPT), *argv],
        input=stdin_text,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    out = (proc.stdout or "").strip()
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        raise IsnadError(
            f"isnad_word.py beklenmeyen çıktı (rc={proc.returncode}): "
            f"{out[:400] or (proc.stderr or '')[:400]}"
        ) from None
    if proc.returncode != 0 or payload.get("error"):
        raise IsnadError(
            f"isnad_word.py hatası: {payload.get('code') or payload.get('error')}"
        )
    return payload


def prepare(meta: dict[str, Any], page: str = "", save_path: str = "") -> dict[str, Any]:
    """Üstveriden İSNAD künye formlarını üret (Word gerekmez)."""
    argv = ["prepare", "--meta-json", "-", "--format", "all"]
    if page:
        argv += ["--page", page]
    if save_path:
        argv += ["--save", save_path]
    return _run(argv, stdin_text=json.dumps(meta, ensure_ascii=False))


def export(log_path: str, fmt: str, out_path: str) -> dict[str, Any]:
    """Atıf günlüğünden RIS/CSL-JSON üret."""
    if fmt not in ("ris", "csljson"):
        raise IsnadError("format 'ris' veya 'csljson' olmalı")
    return _run(["export", "--log", log_path, "--format", fmt, "--out", out_path])


def script_info() -> dict[str, Any]:
    return _run(["--version"])


VERSION = __version__
