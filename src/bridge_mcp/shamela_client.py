"""Shamela MCP'ye (stdio) çağrı yapan istemci sarmalayıcı.

Her çağrı için taze bir session açar; shamela-mcp başlatma maliyeti ~1-2 sn,
v1 için kabul edilebilir. Java/Şamela kök yolları bridge_mcp/__init__.py'den gelir.
"""

import asyncio
import json
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import SHAMELA_ARGS, SHAMELA_COMMAND, SHAMELA_ENV_EXTRA

CALL_TIMEOUT_S = 90.0


class ShamelaError(RuntimeError):
    pass


def _server_params() -> StdioServerParameters:
    env = dict(os.environ)
    env.update(SHAMELA_ENV_EXTRA)
    return StdioServerParameters(
        command=SHAMELA_COMMAND,
        args=list(SHAMELA_ARGS),
        env={k: v for k, v in env.items() if v is not None},
    )


def _extract_json(result: Any) -> Any:
    """MCP CallToolResult içinden metin/JSON yükünü çıkarır."""
    if getattr(result, "isError", False):
        raise ShamelaError(_text_blocks(result) or "shamela tool hatası")
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return None


def _text_blocks(result: Any) -> str:
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def shamela_call(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Shamela MCP tool'unu çağır ve sonucu döndür."""
    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=CALL_TIMEOUT_S)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=CALL_TIMEOUT_S,
            )
    return _extract_json(result)


async def shamela_search_books(query: str, limit: int = 5) -> Any:
    return await shamela_call(
        "shamela_search_books",
        {"query": query, "limit": limit, "response_format": "json"},
    )


async def shamela_get_book(book_id: int) -> Any:
    return await shamela_call(
        "shamela_get_book", {"book_id": book_id, "response_format": "json"}
    )


async def shamela_search_pages(query: str, limit: int = 5) -> Any:
    return await shamela_call(
        "shamela_search_pages", {"query": query, "limit": limit}
    )
