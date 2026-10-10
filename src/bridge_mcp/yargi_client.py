"""yargi-mcp sunucusuna stdio üzerinden soru soran istemci.

Bridge, yargi-mcp'nin modüllerini import etmek yerine (ağır bağımlılıklar ve
yavaş açılış) hazır sunucunun kendi tool'larını çağırır; böylece mevzuat /
Resmî Gazete aramaları tek oturumda yapılabilir.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from . import YARGI_MCP_PATH
from .mcp_stdio import call_tools

YARGI_COMMAND = os.environ.get("YARGI_COMMAND", "uv")
YARGI_ARGS = ["run", "--project", str(YARGI_MCP_PATH), "yargi-mcp"]
YARGI_TIMEOUT_S = float(os.environ.get("YARGI_MCP_TIMEOUT_S", "240"))


async def yargi_calls(
    calls: Iterable[tuple[str, dict[str, Any]]],
    timeout: float = YARGI_TIMEOUT_S,
) -> list[Any]:
    return await call_tools(
        YARGI_COMMAND, YARGI_ARGS, calls, timeout=timeout, label="yargi"
    )


__all__ = ["YARGI_ARGS", "YARGI_COMMAND", "YARGI_TIMEOUT_S", "yargi_calls"]
