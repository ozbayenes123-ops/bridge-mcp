"""bridge-mcp: yerel MCP'leri birleştiren köprü.

Kurulumdaki diğer sunucuların kaynak kodları sys.path ile import edilir.
Varsayılan yollar bu deponun kardeş dizinleridir; hepsi ortam değişkeniyle
geçilebilir:
  YARGI_MCP_PATH        (varsayılan: <kurulum kökü>/yargi-mcp)
  MAKALE_PATH           (varsayılan: <kurulum kökü>/makale)
  ZOTERO_MCP_SRC        (varsayılan: <kurulum kökü>/zotero-mcp-src)
  SHAMELA_ENTRY         (varsayılan: <kurulum kökü>/shamela-mcp/dist/index.js)
  SHAMELA_COMMAND       (varsayılan: node)
  SHAMELA_INSTALL_ROOT  (Shamela 4 kökü; yoksa ayarlanmaz)
  SHAMELA_JRE           (java yolu; verilmezse PATH aranır)
  ISNAD_WORD_SCRIPT     (varsayılan: ~/.commandcode/skills/isnad-word/scripts/isnad_word.py)
"""

import os
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALL_ROOT = _REPO_ROOT.parent


def _path_env(name: str, default: Path) -> str:
    value = os.environ.get(name)
    return value if value else str(default)


def _existing_path_env(name: str, default: Path) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    return str(default) if default.exists() else None


def _java() -> str | None:
    explicit = os.environ.get("SHAMELA_JRE")
    if explicit:
        return explicit
    found = shutil.which("java")
    if found:
        return found
    fallback = Path(r"C:\Program Files\Java\jdk-21\bin\java.exe")
    return str(fallback) if fallback.exists() else None


YARGI_MCP_PATH = _path_env("YARGI_MCP_PATH", _INSTALL_ROOT / "yargi-mcp")
MAKALE_PATH = _path_env("MAKALE_PATH", _INSTALL_ROOT / "makale")
ZOTERO_MCP_SRC = _path_env("ZOTERO_MCP_SRC", _INSTALL_ROOT / "zotero-mcp-src")
SHAMELA_COMMAND = os.environ.get("SHAMELA_COMMAND", "node")
SHAMELA_ARGS = [
    _path_env("SHAMELA_ENTRY", _INSTALL_ROOT / "shamela-mcp" / "dist" / "index.js")
]
SHAMELA_ENV_EXTRA = {
    "SHAMELA_INSTALL_ROOT": _existing_path_env(
        "SHAMELA_INSTALL_ROOT", Path(r"C:\shamela4")
    ),
    "SHAMELA_JRE": _java(),
}

for _p in (YARGI_MCP_PATH, ZOTERO_MCP_SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

__version__ = "0.2.0"
