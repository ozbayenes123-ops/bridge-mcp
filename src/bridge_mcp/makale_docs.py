"""makale belge kökü yardımcıları (bridge zincirleri için ortak).

Zincirlerin hepsi makale deposunun `documents/<slug>/` düzenini kullanır.
Kök `MAKALE_DOCS`, yoksa `<kurulum kökü>/makale/documents` alınır.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from . import MAKALE_PATH

MAKALE_DOCS = Path(os.environ.get("MAKALE_DOCS") or Path(MAKALE_PATH) / "documents")


_TR_MAP = str.maketrans(
    {
        "ı": "i", "İ": "i", "I": "i",
        "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u",
        "ş": "s", "Ş": "s",
        "ö": "o", "Ö": "o",
        "ç": "c", "Ç": "c",
    }
)


def slugify(text: str, fallback: str = "belge") -> str:
    """Türkçe/Unicode metni dosya adı güvenli slug'a çevirir.

    NFKD tek başına noktasız 'ı' ve 'ğ/ş' gibi harfleri doğru indirgemediği
    için (ör. "Yargıtay" -> "yargtay") açık bir Türkçe harf eşlemesi uygular.
    """
    text = unicodedata.normalize("NFKD", (text or "").translate(_TR_MAP))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:48] or fallback


def doc_dir(slug: str, create: bool = False) -> Path:
    """Belge klasörünü döndürür; `create=True` ise oluşturur."""
    slug = (slug or "").strip().strip("/\\")
    if not slug:
        raise ValueError("slug zorunlu")
    path = MAKALE_DOCS / slug
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def translation_files(slug: str) -> list[Path]:
    """Belge klasöründeki _tr.txt dosyaları (taslaklar hariç)."""
    path = MAKALE_DOCS / (slug or "").strip()
    if not path.is_dir():
        return []
    out = [
        p
        for p in sorted(path.glob("*_tr.txt"))
        if not p.stem.endswith("_draft") and not p.stem.endswith("_ham")
    ]
    return out


def write_source(slug: str, file_name: str, text: str, header_lines: list[str] | None = None) -> Path:
    """Belge klasörüne kaynak metin yazar (İSNAD/karar/Şamile alıntıları)."""
    target = doc_dir(slug, create=True) / file_name
    body = ""
    if header_lines:
        body = "\n".join(header_lines) + "\n\n"
    target.write_text(body + text, encoding="utf-8")
    return target


def merge_config(slug: str, metadata: dict[str, Any], extra: dict[str, Any] | None = None) -> Path:
    """config.json'a bridge üstverisini işler (var olan alanları korur)."""
    path = doc_dir(slug, create=True) / "config.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    bridge = dict(data.get("bridge_metadata") or {})
    bridge.update(metadata)
    bridge["updated_at"] = datetime.now().isoformat(timespec="seconds")
    data["bridge_metadata"] = bridge
    if extra:
        data.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


__all__ = [
    "MAKALE_DOCS",
    "doc_dir",
    "merge_config",
    "slugify",
    "translation_files",
    "write_source",
]
