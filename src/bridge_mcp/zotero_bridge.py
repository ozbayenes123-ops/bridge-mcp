"""zotero-mcp kaynağından client.py'yi paket __init__'ini çalıştırmadan yükler.

zotero_mcp/__init__.py mcp 2.x API'sine (MCPServer) bağımlı; bridge mcp 1.x
kullanır. client.py'nin kendisi mcp istemediği için importlib ile tek başına
yüklenir.
"""

import importlib.util
import os
from pathlib import Path
from typing import Any

from . import ZOTERO_MCP_SRC

ZOTERO_CLIENT_PATH = Path(ZOTERO_MCP_SRC) / "zotero_mcp" / "client.py"

_module: Any = None


def _load():
    global _module
    if _module is None:
        if not ZOTERO_CLIENT_PATH.exists():
            raise FileNotFoundError(f"zotero client bulunamadı: {ZOTERO_CLIENT_PATH}")
        spec = importlib.util.spec_from_file_location(
            "zotero_client_standalone", ZOTERO_CLIENT_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _module = mod
    return _module


def get_zotero_client():
    return _load().get_zotero_client()
