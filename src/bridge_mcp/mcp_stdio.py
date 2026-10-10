"""Genel stdio MCP istemcisi.

Yerel MCP sunucularını (zotero-mcp.exe, `uv run --project ... makale serve`)
tek bir oturumda çağırır: oturum açma maliyeti bir kez ödenir, birden çok
tool çağrısı aynı süreç üzerinde yapılır.

Tüm bloke edici kısım daemon iş parçacığında çalışır (bkz. _util), böylece
bir sunucu asılı kalsa bile bridge MCP döngüsü donmaz.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Iterable, Sequence

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ._util import BridgeTimeout, run_in_daemon

DEFAULT_TIMEOUT_S = 180.0


class StdioMcpError(RuntimeError):
    """Yerel MCP sunucusu çağrısı başarısız oldu."""


def _text_blocks(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def extract_json(result: Any) -> Any:
    """MCP CallToolResult içinden metin/JSON yükünü çıkarır."""
    if getattr(result, "isError", False):
        raise StdioMcpError(_text_blocks(result) or "tool hatası")
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return None


async def _session_calls(
    command: str,
    args: Sequence[str],
    calls: Sequence[tuple[str, dict[str, Any]]],
    env_extra: dict[str, str] | None,
) -> list[Any]:
    env = dict(os.environ)
    env.update(env_extra or {})
    params = StdioServerParameters(
        command=command, args=list(args), env={k: v for k, v in env.items() if v is not None}
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            out: list[Any] = []
            for tool, arguments in calls:
                result = await session.call_tool(tool, arguments=arguments or {})
                out.append(extract_json(result))
            return out


async def call_tools(
    command: str,
    args: Sequence[str],
    calls: Iterable[tuple[str, dict[str, Any]]],
    *,
    env_extra: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    label: str = "mcp",
) -> list[Any]:
    """Bir sunucu oturumu açıp verilen tool çağrılarını sırayla yapar."""
    call_list = list(calls)
    if not call_list:
        return []

    def _job() -> list[Any]:
        return asyncio.run(_session_calls(command, args, call_list, env_extra))

    return await asyncio.to_thread(run_in_daemon, _job, timeout, label)


__all__ = [
    "BridgeTimeout",
    "DEFAULT_TIMEOUT_S",
    "StdioMcpError",
    "call_tools",
    "extract_json",
]
