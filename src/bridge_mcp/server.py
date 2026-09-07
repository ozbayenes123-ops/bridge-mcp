"""bridge-mcp sunucusu: birleşik (kompozit) tool'lar.

Orkestrasyon kararı LLM'de kalır; bu tool'lar yalnızca
tekrarlanan zincirleri tek çağrıya indirir.
"""

import asyncio
import json
from pathlib import Path
from tempfile import gettempdir

from mcp.server.fastmcp import FastMCP

from . import __version__
from . import isnad
from .shamela_client import ShamelaError, shamela_get_book, shamela_search_books
from .improvements import ImprovementError, list_improvements, log_improvement, set_status
from .zotero_bridge import get_zotero_client
from .yargi_bridge import cek_ve_yaz

mcp = FastMCP(
    "bridge",
    instructions=(
        "Yerel MCP'ler arası köprü. citation_search/isnad_kunye Zotero+Shamela, "
        "yargi_makale_cek yargi+makale zincirlerini tek çağrıda çalıştırır. "
        "Bridge bağlı değilse skill'ler doğrudan zotero_/shamela_ tool'larıyla "
        "çalışmaya devam eder. İşlem sonunda somut bir eksiklik/hata/özellik "
        "fikri tespit edilirse improvement_log ile kaydedilir; improvement_list "
        "açık kayıtları gösterir, improvement_resolve yapıldı/iptal olarak "
        "kapatır. Düzeltme kararı orkestratördedir; bridge kendi kodunu düzenlemez."
    ),
)


# ---------------------------------------------------------------- citation_search

async def citation_search(query: str, limit: int = 5) -> str:
    """Zotero'da ara; sonuç yoksa Shamela katalogunda ara. Kaynak etiketli döner."""
    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "query zorunlu"}, ensure_ascii=False)

    zotero_hits: list[dict] = []
    zotero_error = None
    try:
        zot = get_zotero_client()
        for qmode in ("titleCreatorYear", "everything"):
            items = zot.items(q=query, qmode=qmode, limit=limit)
            if isinstance(items, dict):
                items = items.get("items", [])
            if items:
                break
        for it in items or []:
            data = it.get("data", {})
            if data.get("itemType") == "attachment":
                continue
            zotero_hits.append(
                {
                    "key": data.get("key"),
                    "itemType": data.get("itemType"),
                    "title": data.get("title"),
                    "creators": [
                        c.get("lastName") or c.get("name")
                        for c in (data.get("creators") or [])
                        if isinstance(c, dict)
                    ][:4],
                    "date": data.get("date"),
                    "source": "zotero",
                }
            )
    except Exception as exc:  # Zotero kapalı olabilir
        zotero_error = f"{type(exc).__name__}: {exc}"

    response: dict = {"query": query, "zotero": zotero_hits, "shamela": []}
    if zotero_error:
        response["zotero_error"] = zotero_error

    if not zotero_hits:
        try:
            books = await shamela_search_books(query, limit=limit)
            if isinstance(books, dict):
                entries = (
                    books.get("results")
                    or books.get("books")
                    or books.get("structuredContent")
                    or []
                )
            elif isinstance(books, list):
                entries = books
            else:
                entries = []
            for b in entries:
                if not isinstance(b, dict):
                    continue
                authors = [a for a in (b.get("authors") or []) if isinstance(a, dict)]
                response["shamela"].append(
                    {
                        "book_id": b.get("book_id"),
                        "book_name": b.get("book_name"),
                        "author_name": b.get("author_name")
                        or (authors[0].get("author_name") if authors else None),
                        "death_year": b.get("death_year")
                        or (authors[0].get("death_year") if authors else None),
                        "downloaded": b.get("downloaded"),
                        "source": "shamela",
                    }
                )
        except ShamelaError as exc:
            response["shamela_error"] = str(exc)

    return json.dumps(response, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- isnad_kunye

def _zotero_meta(item_key: str) -> dict:
    zot = get_zotero_client()
    item = zot.item(item_key)
    data = item.get("data", item) if isinstance(item, dict) else {}
    if not data:
        raise ValueError(f"Zotero item bulunamadı: {item_key}")
    return data


async def _shamela_meta(book_id: int) -> dict:
    book = await shamela_get_book(book_id)
    if isinstance(book, dict):
        book = book.get("book", book)
    if not isinstance(book, dict) or not book.get("book_name"):
        raise ValueError(f"Shamela kitap bulunamadı: {book_id}")
    authors = [a for a in (book.get("authors") or []) if isinstance(a, dict)]
    author_name = (authors[0].get("author_name") if authors else "") or ""
    death_year = authors[0].get("death_year") if authors else None
    return {
        "itemKey": f"shamela-{book_id}",
        "itemType": "book",
        "title": book.get("book_name", ""),
        "shortTitle": book.get("book_name", ""),
        "creators": [{"name": author_name}] if author_name else [],
        "date": str(death_year or book.get("book_date") or ""),
        "extra": f"Şamela kitap no: {book_id}",
    }


async def isnad_kunye(
    item_key: str = "",
    shamela_book_id: int = 0,
    page: str = "",
) -> str:
    """Zotero (veya Shamela) üstverisinden İSNAD künye formlarını üret.

    prepare çıktısı gözle `isnad-kurallari.md`'ye karşı doğrulanmalıdır;
    eksik alan uydurulmaz, kullanıcıya bildirilir.
    """
    if not item_key and not shamela_book_id:
        return json.dumps(
            {"error": "item_key veya shamela_book_id verilmeli"}, ensure_ascii=False
        )

    try:
        if item_key:
            meta = _zotero_meta(item_key)
            source = "zotero"
        else:
            meta = await _shamela_meta(shamela_book_id)
            source = "shamela"
    except Exception as exc:
        return json.dumps(
            {"error": f"üstveri alınamadı: {type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )

    save_path = str(
        Path(gettempdir()) / f"isnad-prepare-{meta.get('itemKey') or 'x'}.json"
    )
    try:
        prepared = await asyncio.to_thread(
            isnad.prepare, meta, page=page, save_path=save_path
        )
    except isnad.IsnadError as exc:
        return json.dumps({"error": str(exc), "meta": meta}, ensure_ascii=False)

    return json.dumps(
        {"source": source, "meta": meta, "prepared": prepared},
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- citation_export

async def citation_export(log_path: str, fmt: str = "ris", out_path: str = "") -> str:
    """İsnad atıf günlüğünden RIS/CSL-JSON üret (Zotero File>Import elle yapılır)."""
    if not log_path:
        return json.dumps({"error": "log_path zorunlu"}, ensure_ascii=False)
    out_ext = "ris" if fmt == "ris" else "json"
    out_path = out_path or str(Path(gettempdir()) / f"isnad-export.{out_ext}")
    try:
        result = await asyncio.to_thread(isnad.export, log_path, fmt, out_path)
    except isnad.IsnadError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    result["output_path"] = out_path
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- yargi_makale_cek

async def yargi_makale_cek(
    sorgu: str,
    slug: str = "",
    document_id: str = "",
    birim_adi: str = "ALL",
) -> str:
    """Bedesten'de karar arar, ilk (veya document_id ile seçilen) kararın
    markdown'ını makale documents/<slug>/ altına yazar."""
    try:
        result = await cek_ve_yaz(
            phrase=sorgu,
            slug=slug,
            document_id=document_id,
            birim_adi=birim_adi,
        )
    except Exception as exc:
        # 429 dahil: structured hata döndür, crash etme
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}", "rate_limited": "429" in str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- improvement_log

async def improvement_log(
    konu: str,
    tip: str = "eksik",
    hedef: str = "bridge",
    kaynak_tool: str = "",
    detay: str = "",
) -> str:
    """Bir işlemde keşfedilen eksiklik/hata/özellik fikrini kalıcı kaydet.

    tip: bug | eksik | ozellik | iyilestirme
    hedef: bridge | shamela | yargi | makale | zotero | skill | diger
    Kayıtlar improvement_list ile okunur; düzeltme bir sonraki oturumda
    orkestratör tarafından yapılır. Sadece gerçek gözlemler kaydedilir,
    varsayım/kurgu kaydedilmez.
    """
    try:
        record = log_improvement(
            konu=konu, tip=tip, hedef=hedef, kaynak_tool=kaynak_tool, detay=detay
        )
    except ImprovementError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps(
        {"logged": True, **record}, ensure_ascii=False, indent=2
    )


async def improvement_list(status: str = "acik", hedef: str = "") -> str:
    """Açık (veya tüm) eksiklik/hata kayıtlarını listeler."""
    if status not in ("acik", "yapildi", "iptal", "hepsi"):
        return json.dumps({"error": "status 'acik'|'yapildi'|'iptal'|'hepsi' olmalı"}, ensure_ascii=False)
    records = list_improvements(status="" if status == "hepsi" else status, hedef=hedef)
    return json.dumps(
        {"toplam": len(records), "kayitlar": records}, ensure_ascii=False, indent=2
    )


async def improvement_resolve(improvement_id: str, durum: str = "yapildi") -> str:
    """Kayıt durumunu günceller (acik → yapildi/iptal)."""
    try:
        record = set_status(improvement_id, durum)
    except ImprovementError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps({"updated": record}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- kayıt

async def bridge_health() -> str:
    """Bağlı bileşenlerin durumunu bildirir (import/spawn kontrolü)."""
    info: dict = {"version": __version__, "components": {}}
    try:
        get_zotero_client()
        info["components"]["zotero"] = "ok"
    except Exception as exc:
        info["components"]["zotero"] = f"hata: {exc}"
    try:
        await shamela_get_book(1)
        info["components"]["shamela"] = "ok"
    except Exception as exc:
        info["components"]["shamela"] = f"hata: {type(exc).__name__}: {exc}"
    try:
        import bedesten_mcp_module.client  # noqa: F401

        info["components"]["yargi"] = "ok"
    except Exception as exc:
        info["components"]["yargi"] = f"hata: {exc}"
    info["components"]["isnad_script"] = (
        "ok" if isnad.ISNAD_SCRIPT.exists() else "betik bulunamadı"
    )
    return json.dumps(info, ensure_ascii=False, indent=2)


mcp.tool()(citation_search)
mcp.tool()(isnad_kunye)
mcp.tool()(citation_export)
mcp.tool()(yargi_makale_cek)
mcp.tool()(bridge_health)
mcp.tool()(improvement_log)
mcp.tool()(improvement_list)
mcp.tool()(improvement_resolve)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
