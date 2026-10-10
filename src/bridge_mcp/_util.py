"""Küçük yardımcılar: zaman aşımına dayanıklı daemon çalıştırıcı.

Neden gerekli: yerel MCP sunucularını (node/uv alt süreçleri) başlatan
istemciler `asyncio.wait_for` ile kesildiğinde anyio temizliği asılı
kalabiliyor ve MCP olay döngüsünü bloke ediyor. Bu yüzden bloke edebilecek
işleri ayrı bir daemon iş parçacığına taşıyıp ana döngüyü hiç beklemiyoruz.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class BridgeTimeout(RuntimeError):
    """Bir alt işlem verilen süre içinde yanıt vermedi."""


def run_in_daemon(fn: Callable[[], Any], timeout: float, label: str = "bridge") -> Any:
    """`fn`'i daemon iş parçacığında çalıştır, `timeout` saniyede kesin dön.

    Süre dolduğunda BridgeTimeout yükseltilir; iş parçacığı daemon olduğu
    için asılı kalsa bile sunucu ayakta kalır ve süreç çıkışını engellemez.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - çağırana aynen iletilir
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=runner, daemon=True, name=f"{label}-worker").start()
    if not done.wait(timeout):
        raise BridgeTimeout(f"{label}: {timeout:.0f} sn içinde yanıt yok")
    if "error" in box:
        raise box["error"]
    return box.get("value")
