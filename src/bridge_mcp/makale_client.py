"""makale MCP sunucusuna (`uv run --project ... makale serve`) stdio istemcisi.

makale sunucusu mcp 2.x API'siyle yazılmış; bridge mcp 1.x kullandığı için
modülleri import etmek yerine sunucunun kendi tool'larını çağırıyoruz.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from . import MAKALE_PATH
from .mcp_stdio import call_tools

MAKALE_COMMAND = os.environ.get("MAKALE_COMMAND", "uv")
MAKALE_ARGS = ["run", "--project", str(MAKALE_PATH), "makale", "serve"]
MAKALE_TIMEOUT_S = float(os.environ.get("MAKALE_MCP_TIMEOUT_S", "300"))


async def makale_calls(
    calls: Iterable[tuple[str, dict[str, Any]]],
    timeout: float = MAKALE_TIMEOUT_S,
) -> list[Any]:
    """makale sunucusunda verilen tool çağrılarını tek oturumda çalıştırır."""
    return await call_tools(
        MAKALE_COMMAND,
        MAKALE_ARGS,
        calls,
        timeout=timeout,
        label="makale",
    )


__all__ = ["MAKALE_ARGS", "MAKALE_COMMAND", "MAKALE_TIMEOUT_S", "makale_calls"]
