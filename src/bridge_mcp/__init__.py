"""bridge-mcp: yerel MCP'leri birleştiren köprü.

Kurulumdaki diğer sunucuların kaynak kodları sys.path ile import edilir;
ortam değişkenleriyle geçilebilir:
  YARGI_MCP_PATH   (varsayılan C:/dev/mcp/yargi-mcp)
  ZOTERO_MCP_SRC   (varsayılan C:/dev/mcp/zotero-mcp-src)
  SHAMELA_CMD      (varsayılan: node C:/dev/mcp/shamela-mcp/dist/index.js)
"""

import os
import sys

YARGI_MCP_PATH = os.environ.get("YARGI_MCP_PATH", r"C:\dev\mcp\yargi-mcp")
ZOTERO_MCP_SRC = os.environ.get("ZOTERO_MCP_SRC", r"C:\dev\mcp\zotero-mcp-src")
SHAMELA_COMMAND = os.environ.get("SHAMELA_COMMAND", "node")
SHAMELA_ARGS = [
    os.environ.get("SHAMELA_ENTRY", r"C:\dev\mcp\shamela-mcp\dist\index.js")
]
SHAMELA_ENV_EXTRA = {
    "SHAMELA_INSTALL_ROOT": os.environ.get("SHAMELA_INSTALL_ROOT", r"C:\shamela4"),
    "SHAMELA_JRE": os.environ.get(
        "SHAMELA_JRE", r"C:\Program Files\Java\jdk-21\bin\java.exe"
    ),
}

for _p in (YARGI_MCP_PATH, ZOTERO_MCP_SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

__version__ = "0.1.0"
