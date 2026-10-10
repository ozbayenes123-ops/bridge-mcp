"""zotero-mcp sunucusuna stdio üzerinden yazma çağrıları.

Yerel Zotero API'sine yazan tool'lar (item oluşturma, dosya eki) zotero-mcp
sunucusunda bulunur; bridge onları kendi venv'ine import etmek yerine
sunucunun kendisine çağrı yapar (mcp sürüm farkı: zotero-mcp mcp 2.x).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

from .mcp_stdio import call_tools

ZOTERO_COMMAND = os.environ.get(
    "ZOTERO_COMMAND", str(Path.home() / ".local" / "bin" / "zotero-mcp.exe")
)
ZOTERO_ARGS: list[str] = []
ZOTERO_TIMEOUT_S = float(os.environ.get("ZOTERO_MCP_TIMEOUT_S", "180"))

_KEY_RE = re.compile(r"key:\s*`([A-Za-z0-9]+)`")


class ZoteroWriteError(RuntimeError):
    """Zotero yazma çağrısı başarısız (mesaj kullanıcıya gösterilebilir)."""


def _env_extra() -> dict[str, str]:
    return {"ZOTERO_LOCAL": os.environ.get("ZOTERO_LOCAL", "true")}


async def zotero_calls(
    calls: Iterable[tuple[str, dict[str, Any]]],
    timeout: float = ZOTERO_TIMEOUT_S,
) -> list[Any]:
    return await call_tools(
        ZOTERO_COMMAND,
        ZOTERO_ARGS,
        calls,
        env_extra=_env_extra(),
        timeout=timeout,
        label="zotero",
    )


def parse_new_key(text: Any) -> str:
    """`Created case — key: `ABCD1234`` metninden item anahtarını çıkarır."""
    if not isinstance(text, str):
        raise ZoteroWriteError(f"beklenmeyen yanıt tipi: {type(text).__name__}")
    if text.lstrip().lower().startswith("error"):
        raise ZoteroWriteError(text.strip())
    match = _KEY_RE.search(text)
    if not match:
        raise ZoteroWriteError(f"item anahtarı okunamadı: {text.strip()[:200]}")
    return match.group(1)


__all__ = [
    "ZOTERO_ARGS",
    "ZOTERO_COMMAND",
    "ZOTERO_TIMEOUT_S",
    "ZoteroWriteError",
    "parse_new_key",
    "zotero_calls",
]
