"""Keşfedilen eksiklik/hata kayıtları — kalıcı geri bildirim halkası.

Kayıt yeri: <bridge repo>/data/improvements.jsonl (her satır bir JSON kayıt).
Bu dosya git ile izlenir; bir sonraki oturumda orkestratör (LLM)
bu kayıtları okuyup düzeltme/özellik işi olarak gerçekleştirir.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(
    os.environ.get("BRIDGE_DATA_DIR", Path(__file__).resolve().parent.parent.parent / "data")
)
LOG_PATH = DATA_DIR / "improvements.jsonl"

VALID_TYPES = ("bug", "eksik", "ozellik", "iyilestirme")
VALID_TARGETS = ("bridge", "shamela", "yargi", "makale", "zotero", "skill", "diger")


class ImprovementError(RuntimeError):
    pass


def log_improvement(
    konu: str,
    tip: str = "eksik",
    hedef: str = "bridge",
    kaynak_tool: str = "",
    detay: str = "",
) -> dict[str, Any]:
    if not konu or not konu.strip():
        raise ImprovementError("konu zorunlu")
    tip = tip if tip in VALID_TYPES else "eksik"
    hedef = hedef if hedef in VALID_TARGETS else "diger"
    record = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
        "tarih": datetime.now().isoformat(timespec="seconds"),
        "konu": konu.strip(),
        "tip": tip,
        "hedef": hedef,
        "kaynak_tool": kaynak_tool.strip(),
        "detay": detay.strip(),
        "durum": "acik",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_improvements(status: str = "", hedef: str = "") -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    out = []
    with LOG_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if status and rec.get("durum") != status:
                continue
            if hedef and rec.get("hedef") != hedef:
                continue
            out.append(rec)
    return out


def set_status(improvement_id: str, durum: str) -> dict[str, Any]:
    """Kaydın durumunu günceller (acik → yapildi/iptal)."""
    if durum not in ("acik", "yapildi", "iptal"):
        raise ImprovementError("durum 'acik' | 'yapildi' | 'iptal' olmalı")
    if not LOG_PATH.exists():
        raise ImprovementError("kayıt dosyası yok")
    lines: list[str] = []
    updated: dict[str, Any] | None = None
    for line in LOG_PATH.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("id") == improvement_id:
            rec["durum"] = durum
            updated = rec
        lines.append(json.dumps(rec, ensure_ascii=False))
    if updated is None:
        raise ImprovementError(f"kayıt bulunamadı: {improvement_id}")
    LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated
