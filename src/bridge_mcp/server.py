"""bridge-mcp sunucusu: birleşik (kompozit) tool'lar.

Orkestrasyon kararı LLM'de kalır; bu tool'lar yalnızca
tekrarlanan zincirleri tek çağrıya indirir.
"""

import asyncio
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import MAKALE_PATH, SHAMELA_ARGS, SHAMELA_COMMAND
from . import __version__
from . import isnad
from ._util import BridgeTimeout, run_in_daemon
from .makale_docs import merge_config, slugify, translation_files, write_source
from .shamela_client import (
    ShamelaError,
    shamela_get_book,
    shamela_get_citation,
    shamela_get_page,
    shamela_search_books,
    shamela_search_pages,
)
from .improvements import ImprovementError, list_improvements, log_improvement, set_status
from .zotero_bridge import get_zotero_client
from .zotero_client import ZOTERO_COMMAND, ZoteroWriteError, parse_new_key, zotero_calls
# yargi_bridge cagri aninda (tembel) import edilir: yargi-mcp kurulu olmayabilir

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

def _compact_yargi(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "documentId": entry.get("documentId"),
        "birimAdi": entry.get("birimAdi"),
        "esasNo": entry.get("esasNo"),
        "kararNo": entry.get("kararNo"),
        "kararTarihi": entry.get("kararTarihiStr") or entry.get("kararTarihi"),
        "source": "yargi",
    }


def _yargi_search_sync(query: str, page: int = 1) -> dict[str, Any]:
    """Bedesten araması: import + ağ aynı iş parçacığında (olay döngüsü bloke olmaz)."""
    from .yargi_bridge import bedesten_search

    return asyncio.run(bedesten_search(query, page=page))


async def _yargi_hits(query: str, limit: int, timeout: float) -> tuple[list[dict], str | None]:
    try:
        result = await asyncio.to_thread(
            run_in_daemon, lambda: _yargi_search_sync(query), timeout, "yargi"
        )
    except BridgeTimeout as exc:
        return [], f"zaman aşımı: {exc}"
    except Exception as exc:  # yargi kurulu değil / ağ hatası
        return [], f"{type(exc).__name__}: {exc}"
    entries = result.get("entries") or []
    return [_compact_yargi(e) for e in entries[:limit]], None


async def citation_search(
    query: str,
    limit: int = 5,
    kaynaklar: str = "zotero,shamela,yargi",
    yargi_timeout_s: float = 30.0,
) -> str:
    """Zotero'da ara; Şamile ve Yargı (Bedesten) bacakları `kaynaklar` ile seçilir.

    `kaynaklar`: "zotero,shamela,yargi" gibi virgüllü liste.
    Şamile yalnızca Zotero boş dönerse sorgulanır (katalog araması yavaş).
    Yargı bacağı Türk mahkeme kararlarını getirir (Bedesten).
    """
    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "query zorunlu"}, ensure_ascii=False)

    wanted = {k.strip().lower() for k in (kaynaklar or "").split(",") if k.strip()}

    zotero_hits: list[dict] = []
    zotero_error = None
    items: list = []
    if "zotero" in wanted:
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

    response: dict = {"query": query, "zotero": zotero_hits, "shamela": [], "yargi": []}
    if zotero_error:
        response["zotero_error"] = zotero_error

    if "yargi" in wanted:
        hits, error = await _yargi_hits(query, limit, yargi_timeout_s)
        response["yargi"] = hits
        if error:
            response["yargi_error"] = error

    if not zotero_hits and "shamela" in wanted:
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
        from .yargi_bridge import cek_ve_yaz
    except Exception as exc:
        return json.dumps(
            {
                "error": f"yargi modulu yuklenemedi: {type(exc).__name__}: {exc}",
                "hint": "yargi-mcp deposu kurulum kokunde mi ve YARGI_MCP_PATH dogru mu?",
            },
            ensure_ascii=False,
        )

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


# ---------------------------------------------------------------- yargi → zotero

def _yargi_fetch_sync(document_id: str, sorgu: str) -> dict[str, Any]:
    """Kararı Bedesten'den çeker (import + ağ aynı iş parçacığında)."""
    from .yargi_bridge import bedesten_document, bedesten_search

    async def _run() -> dict[str, Any]:
        if document_id:
            return {
                "chosen": {"documentId": document_id},
                "doc": await bedesten_document(document_id),
            }
        results = await bedesten_search(sorgu)
        entries = results.get("entries") or []
        if not entries:
            return {"chosen": None, "doc": None, "total": results.get("total")}
        entry = entries[0]
        return {
            "chosen": entry,
            "doc": await bedesten_document(entry["documentId"]),
        }

    return asyncio.run(_run())


_MAHKEME_RE = re.compile(r"([^\n\r]{3,80}?Mahkemesi)")
_DIGIT_RE = re.compile(r"\d")


def _clean_court(raw: str) -> str:
    """'… İstanbul 19. Asliye Ticaret Mahkemesi' gibi adları toparlar."""
    text = " ".join(raw.split())
    # Baştaki tırnak/iki nokta gibi artıkları at.
    text = text.strip(" :\"'“”،,;")
    parts = text.split()
    if len(parts) <= 8:
        return text
    # Uzun (gürültülü) eşleşmelerde sayı içeren kısımdan başlat: ör. '19. Asliye…'
    window = parts[-8:]
    for i, token in enumerate(window):
        if _DIGIT_RE.search(token) and i + 1 < len(window):
            return " ".join(window[i:])
    return " ".join(window)


def _meta_from_markdown(content: str) -> dict[str, str]:
    """document_id ile gidildiğinde arama üstverisi yok; karar metninden çıkar."""
    out: dict[str, str] = {}
    esas = re.search(r"Esas\s*(?:No|Numaras[ıi])?\s*[:\-]?\s*(\d{4}/\d+)", content)
    karar = re.search(r"Karar\s*(?:No|Numaras[ıi])?\s*[:\-]?\s*(\d{4}/\d+)", content)
    tarih = re.search(
        r"Karar\s*Tarihi\s*[:\-]?\s*(\d{1,2}[./]\d{1,2}[./]\d{4})", content
    )
    if esas:
        out["esasNo"] = esas.group(1)
    if karar:
        out["kararNo"] = karar.group(1)
    if tarih:
        out["kararTarihiStr"] = tarih.group(1)
    courts = [_clean_court(m.group(1)) for m in _MAHKEME_RE.finditer(content)]
    if courts:
        # En uzun (en çok bilgi taşıyan) mahkeme adını seç.
        out["birimAdi"] = max(courts, key=len)
    return out


def _item_body(
    item_type: str, chosen: dict[str, Any], doc: dict[str, Any]
) -> dict[str, Any]:
    """Zotero item gövdesi.

    `case` tipinde başlık alanı `caseName`'dir; `title` gönderilirse Zotero
    yok sayar ve item "Untitled" görünür.
    """
    birim = chosen.get("birimAdi") or ""
    esas = chosen.get("esasNo") or ""
    karar = chosen.get("kararNo") or ""
    tarih = str(chosen.get("kararTarihiStr") or chosen.get("kararTarihi") or "")
    title = " ".join(
        part
        for part in [
            birim,
            f"E. {esas}" if esas else "",
            f"K. {karar}" if karar else "",
        ]
        if part
    )
    fallback = doc.get("title") or "Bedesten kararı"
    title = title or fallback

    body: dict[str, Any] = {}
    if item_type == "case":
        body["caseName"] = title
        if birim:
            body["court"] = birim
        if tarih:
            body["dateDecided"] = tarih
    else:
        body["title"] = title
        if tarih:
            body["date"] = tarih
    if doc.get("source_url"):
        body["url"] = doc["source_url"]
    body["extra"] = (
        f"Bedesten document_id: {chosen.get('documentId')}\n"
        f"Esas/Karar: {esas or '?'}/{karar or '?'}\n"
        "Kaynak: bridge-mcp yargi_zotero_kaydet"
    )
    return {k: v for k, v in body.items() if v}


def _zotero_fields(chosen: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Geriye dönük uyum: case gövdesinden başlık/extra üretir."""
    body = _item_body("case", chosen, doc)
    return {"title": body.get("caseName", ""), "extra": body.get("extra", "")}



async def yargi_zotero_kaydet(
    sorgu: str = "",
    document_id: str = "",
    koleksiyon: str = "",
    etiketler: str = "",
    dosya_ekle: bool = True,
    birim_adi: str = "",
    esas_no: str = "",
    karar_no: str = "",
    karar_tarihi: str = "",
    timeout_s: float = 120.0,
) -> str:
    """Bedesten kararını Zotero'ya item olarak kaydeder, markdown'ı ek yapar.

    Karar `document_id` ile veya `sorgu` ile (ilk isabet) seçilir.
    `document_id` ile gelindiğinde birim/esas/karar bilgisi karar metninden
    çıkarılır; eksik kalırsa `birim_adi`, `esas_no`, `karar_no`,
    `karar_tarihi` parametreleriyle elle verilebilir.
    `koleksiyon`: Zotero koleksiyon anahtarı; `etiketler`: virgüllü liste.
    """
    if not sorgu and not document_id:
        return json.dumps({"error": "sorgu veya document_id zorunlu"}, ensure_ascii=False)

    try:
        fetched = await asyncio.to_thread(
            run_in_daemon,
            lambda: _yargi_fetch_sync(document_id, sorgu),
            timeout_s,
            "yargi",
        )
    except BridgeTimeout as exc:
        return json.dumps({"error": f"yargi zaman aşımı: {exc}"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"error": f"yargi: {type(exc).__name__}: {exc}"}, ensure_ascii=False
        )

    chosen = fetched.get("chosen")
    doc = fetched.get("doc") or {}
    if not chosen or not doc:
        return json.dumps(
            {"found": False, "query": sorgu, "total": fetched.get("total", 0)},
            ensure_ascii=False,
        )

    content = doc.get("markdown_content") or ""
    if not content:
        return json.dumps(
            {"error": f"karar içeriği boş (id={doc.get('documentId') or document_id})"},
            ensure_ascii=False,
        )

    slug = slugify(chosen.get("kararNo") or sorgu or document_id, fallback="bedesten-karar")
    md_path = Path(gettempdir()) / f"bedesten-{slug}.md"
    md_path.write_text(content, encoding="utf-8")

    # document_id ile gelindiyse arama üstverisi yok: karar metninden tamamla.
    derived = _meta_from_markdown(content)
    manual = {
        "birimAdi": birim_adi,
        "esasNo": esas_no,
        "kararNo": karar_no,
        "kararTarihiStr": karar_tarihi,
    }
    chosen = {
        **derived,
        **{k: v for k, v in chosen.items() if v},
        **{k: v for k, v in manual.items() if v},
    }
    tags = [t.strip() for t in (etiketler or "").split(",") if t.strip()]

    def _create_args(item_type: str) -> dict[str, Any]:
        return {
            "item_type": item_type,
            "fields": _item_body(item_type, chosen, doc),
            "tags": tags or None,
            "collection_keys": [koleksiyon] if koleksiyon else None,
        }

    item_key = ""
    used_type = ""
    errors: list[str] = []
    for item_type in ("case", "document"):
        try:
            created = (await zotero_calls([("zotero_create_item", _create_args(item_type))]))[0]
            item_key = parse_new_key(created)
            used_type = item_type
            break
        except (ZoteroWriteError, BridgeTimeout, Exception) as exc:  # noqa: BLE001
            errors.append(f"{item_type}: {exc}")

    if not item_key:
        return json.dumps(
            {"error": "Zotero item oluşturulamadı", "denemeler": errors},
            ensure_ascii=False,
        )

    attachment: Any = None
    if dosya_ekle:
        try:
            attachment = (
                await zotero_calls(
                    [
                        (
                            "zotero_upload_file",
                            {
                                "item_key": item_key,
                                "filepath": str(md_path.resolve()),
                                "title": f"{slug} (Bedesten karar metni)",
                            },
                        )
                    ]
                )
            )[0]
        except Exception as exc:  # noqa: BLE001
            attachment = f"ek yüklenemedi: {type(exc).__name__}: {exc}"

    body_used = _item_body(used_type, chosen, doc)
    return json.dumps(
        {
            "ok": True,
            "item_key": item_key,
            "item_type": used_type,
            "title": body_used.get("caseName") or body_used.get("title"),
            "koleksiyon": koleksiyon or None,
            "etiketler": tags,
            "markdown_path": str(md_path),
            "attachment": attachment,
            "kaynak": {
                "document_id": chosen.get("documentId"),
                "birim_adi": chosen.get("birimAdi"),
                "esas_no": chosen.get("esasNo"),
                "karar_no": chosen.get("kararNo"),
                "karar_tarihi": chosen.get("kararTarihiStr") or chosen.get("kararTarihi"),
                "source_url": doc.get("source_url"),
            },
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- shamela → makale

def _find_first(payload: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    """İç içe yanıtta ilk eşleşen sözlüğü bulur (tool şemaları sürümle değişiyor)."""
    if isinstance(payload, dict):
        if any(k in payload for k in keys):
            return payload
        for value in payload.values():
            found = _find_first(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_first(item, keys)
            if found:
                return found
    return {}


def _first_int(payload: Any, keys: tuple[str, ...]) -> int:
    found = _find_first(payload, keys)
    for key in keys:
        value = found.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _page_text(page: Any) -> tuple[str, str]:
    """(metin, basılı sayfa) döndürür."""
    if isinstance(page, str):
        return page, ""
    data = _find_first(page, ("body", "text", "content")) or {}
    body = data.get("body") or data.get("text") or data.get("content") or ""
    printed = str(data.get("printed_page") or data.get("printedPage") or "")
    part = str(data.get("part") or "")
    if part and printed:
        printed = f"{part}/{printed}"
    return str(body), printed


async def shamela_makale_ata(
    slug: str = "",
    book_id: int = 0,
    page_id: int = 0,
    quote: str = "",
    baslik: str = "",
) -> str:
    """Şamile kitap sayfasını makale belgesine kaynak + İSNAD dipnotu olarak ekler.

    `page_id` verilmezse `quote` ile sayfa aranır (ilk isabet kullanılır).
    Uyarı: alıntı metni yazıldığı gibi doğrulanmalıdır (shamela_verify_quote).
    """
    if not slug:
        return json.dumps({"error": "slug zorunlu"}, ensure_ascii=False)
    if not book_id:
        return json.dumps({"error": "book_id zorunlu"}, ensure_ascii=False)
    if not page_id and not quote:
        return json.dumps(
            {"error": "page_id veya quote verilmeli (basılı sayfa no ile arama yok)"},
            ensure_ascii=False,
        )

    try:
        if not page_id:
            hits = await shamela_search_pages(quote, limit=5)
            page_id = _first_int(hits, ("page_id", "pageId", "pageID"))
            if not page_id:
                return json.dumps(
                    {"found": False, "error": "alıntı için sayfa bulunamadı", "quote": quote},
                    ensure_ascii=False,
                )
        page = await shamela_get_page(book_id, page_id)
        citation = await shamela_get_citation(book_id, page_id, quote or baslik)
    except ShamelaError as exc:
        return json.dumps({"error": f"şamile: {exc}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"error": f"şamile: {type(exc).__name__}: {exc}"}, ensure_ascii=False
        )

    body, printed = _page_text(page)
    if not body.strip():
        return json.dumps(
            {"error": f"sayfa metni boş (book_id={book_id}, page_id={page_id})"},
            ensure_ascii=False,
        )
    if not printed:
        # Şamile sayfa yanıtı basılı numarayı vermezse künye bileşenlerinden al;
        # İSNAD dipnotuna ASLA iç page_id yazılmaz.
        cite_comp = _find_first(citation, ("printed_page",))
        page_no = str(cite_comp.get("printed_page") or "").strip()
        part_no = str(cite_comp.get("part") or "").strip()
        if page_no:
            printed = f"{part_no}/{page_no}" if part_no else page_no

    dipnot = None
    try:
        meta = await _shamela_meta(book_id)
        save_path = str(Path(gettempdir()) / f"isnad-shamela-{book_id}-{page_id}.json")
        dipnot = await asyncio.to_thread(
            isnad.prepare, meta, page=printed or str(page_id), save_path=save_path
        )
    except Exception as exc:  # noqa: BLE001 - künye üretilemezse kaynak yine yazılır
        dipnot = {"error": f"{type(exc).__name__}: {exc}"}

    header = [
        f"<!-- kaynak: Şamile (el-Mektebetü'ş-Şâmile) book_id={book_id} page_id={page_id} -->",
        f"<!-- basılı sayfa: {printed or 'bilinmiyor'} -->",
    ]
    if quote:
        header.append(f"<!-- alıntı (doğrulanmalı): {quote[:200]} -->")
    source_path = write_source(
        slug,
        f"{slug}_samile-b{book_id}-p{page_id}.md",
        body,
        header_lines=header,
    )
    config_path = merge_config(
        slug,
        {
            "source": "shamela",
            "book_id": book_id,
            "page_id": page_id,
            "printed_page": printed or None,
            "quote": quote or None,
            "source_file": source_path.name,
        },
    )

    return json.dumps(
        {
            "ok": True,
            "slug": slug,
            "book_id": book_id,
            "page_id": page_id,
            "printed_page": printed or None,
            "source_path": str(source_path),
            "config_path": str(config_path),
            "citation": citation,
            "dipnot": dipnot,
            "dogrulama_notu": (
                "Alıntıyı shamela_verify_quote ile yazıldığı gibi doğrula; "
                "doğrulama birebir karşılaştırmadır, önce doğrula sonra normalleştir."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- makale_durum

def _issue_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("issues", "uyarilar", "warnings", "problems", "errors"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


async def makale_durum(slug: str = "", timeout_s: float = 300.0) -> str:
    """Belge/proje durumunu tek çağrıda özetler: durum + kalite + atıf + sözlük."""
    from .makale_client import makale_calls

    calls: list[tuple[str, dict[str, Any]]] = [("doc_status", {}), ("project_stats", {})]
    tr_files = translation_files(slug) if slug else []
    if tr_files:
        target = str(tr_files[0].resolve())
        calls += [
            ("quality_scan", {"path": target}),
            ("citation_check", {"translation_path": target}),
            ("glossary_check", {"path": target}),
        ]

    try:
        results = await makale_calls(calls, timeout=timeout_s)
    except BridgeTimeout as exc:
        return json.dumps({"error": f"makale zaman aşımı: {exc}"}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"error": f"makale: {type(exc).__name__}: {exc}"}, ensure_ascii=False
        )

    payload = dict(zip([name for name, _ in calls], results))
    uyarilar: list[str] = []
    belge_satirlari: list[dict] = []
    if slug:
        doc_status = payload.get("doc_status") or {}
        rows = doc_status.get("documents") if isinstance(doc_status, dict) else []
        belge_satirlari = [
            r for r in (rows or []) if str(r.get("path", "")).startswith(slug)
        ]
        if not tr_files:
            uyarilar.append(f"{slug}: _tr.txt yok (çeviri eksik)")
        if belge_satirlari and not any(r.get("docx") for r in belge_satirlari):
            uyarilar.append(f"{slug}: derlenmiş .docx yok")
        for name in ("quality_scan", "citation_check", "glossary_check"):
            count = _issue_count(payload.get(name))
            if count:
                uyarilar.append(f"{name}: {count} sorun")

    return json.dumps(
        {
            "slug": slug or None,
            "ceviri_dosyalari": [str(p) for p in tr_files],
            "belge_satirlari": belge_satirlari,
            "uyarilar": uyarilar,
            "cagrilar": payload,
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- zotero → Word (canlı atıf)

ZOTERO_LOCAL_API = os.environ.get("ZOTERO_LOCAL_API", "http://localhost:23119/api")
NOTE_TYPES = {"metinici": 0, "dipnot": 1, "sonnot": 2}
ZOTERO_PROFILES = (
    Path(os.environ.get("APPDATA", "")) / "Zotero" / "Zotero" / "Profiles"
)


def _zotero_pref_js(key: str) -> str:
    """Zotero profil prefs.js'inden tek bir tercihi okur."""
    for prefs in sorted(ZOTERO_PROFILES.glob("*/prefs.js")):
        try:
            text = prefs.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(rf'user_pref\("{re.escape(key)}",\s*"([^"]*)"\)', text)
        if match:
            return match.group(1)
    return ""


def zotero_varsayilan_stil() -> tuple[str, str]:
    """Zotero'nun son kullandığı atıf stilini ve yerelini döndürür.

    Kullanıcı Zotero'da İSNAD'ı bir kez seçtiğinde bu ayar kalıcıdır
    (`extensions.zotero.export.lastStyle`), böylece her belgede yeniden
    seçmek gerekmez.
    """
    stil = _zotero_pref_js("extensions.zotero.export.lastStyle") or "isnad-dipnotlu"
    yerel = _zotero_pref_js("extensions.zotero.export.lastLocale") or "tr-TR"
    return stil, yerel


def _local_api(path: str, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(
        f"{ZOTERO_LOCAL_API}{path}", headers={"Zotero-API-Version": "3"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _csl_entries(keys: list[str]) -> list[dict[str, Any]]:
    """Zotero yerel API'sinden CSL JSON + item URI (CSL 'id' alanı URI'dir)."""
    from .word_citation import WordFieldError

    entries: list[dict[str, Any]] = []
    for key in keys:
        data = _local_api(f"/users/0/items/{key}?format=csljson")
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict) or not data:
            raise WordFieldError(f"CSL verisi alınamadı: {key}")
        entries.append({"uri": data.get("id") or "", "csl": data})
    return entries


def _csl_fallback_text(csl: dict[str, Any]) -> str:
    """CSL JSON'dan kaba ama okunur bir atıf metni (İSNAD üretilemezse)."""
    authors = [
        str(a.get("family") or a.get("literal") or "")
        for a in (csl.get("author") or [])
        if isinstance(a, dict)
    ]
    year = ""
    for part in (csl.get("issued") or {}).get("date-parts") or []:
        if part:
            year = str(part[0])
            break
    bits = [b for b in (", ".join(a for a in authors if a), csl.get("title"), year) if b]
    return ", ".join(bits) or "kaynak"


def _isnad_forms_sync(key: str, page: str = "") -> dict[str, str]:
    """İSNAD dipnot/kısa/kaynakça formları (üretilemezse boş sözlük)."""
    try:
        meta = _zotero_meta(key)
        save_path = str(Path(gettempdir()) / f"isnad-word-{key}.json")
        prepared = isnad.prepare(meta, page=page, save_path=save_path)
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(prepared, dict):
        return {}
    return {
        "dipnot": str(prepared.get("dipnot_tam") or ""),
        "kisa": str(prepared.get("kisa_sablon") or ""),
        "kaynakca": str(prepared.get("kaynakca") or ""),
    }


async def zotero_word_atif(
    docx_path: str,
    item_keys: str = "",
    sorgu: str = "",
    konum: str = "son",
    locator: str = "",
    stil: str = "",
    atif_tipi: str = "dipnot",
    yazi_tipi: str = "Times New Roman",
    bibliyografya: bool = False,
    stil_ayarla: bool = True,
    yedek: bool = True,
) -> str:
    """Word belgesine Zotero eklentisinin TANIDIĞI canlı atıf alanı yazar.

    Alan kodu Zotero'nun kendi biçimidir (`ADDIN ZOTERO_ITEM CSL_CITATION …`):
    belge Word'de Zotero ile yenilendiğinde atıf Zotero'nun yönettiği gerçek
    bir atfa dönüşür (stil değiştirme, kaynakça, yenileme normal çalışır).

    `item_keys`: Zotero item anahtarı/anahtarları (virgüllü); boşsa `sorgu`
    ile Zotero'da aranır (ilk sonuç). `konum`: "son" = belge sonuna ekle, ya
    da belgede değiştirilecek işaret metni (ör. "{{ATIF}}"). `atif_tipi`:
    dipnot | metinici | sonnot.
    `stil` boş bırakılırsa belgede yazılı stil, yoksa Zotero'nun son kullandığı
    stil (prefs.js: extensions.zotero.export.lastStyle) kullanılır; yani stil
    bir kez seçilir, sonraki belgelerde tekrar seçmek gerekmez. Görünen metin
    İSNAD betiğiyle üretilir; ikinci ve sonraki atıflarda kısa biçimi Zotero'nun
    citeproc'u belirler (belge yenilendiğinde).
    """
    from .word_citation import (
        DocxPackage,
        WordFieldError,
        bibliography_instruction,
        build_citation_payload,
        build_prefs_json,
        citation_instruction,
        prefs_instructions,
        style_url,
    )

    try:
        keys = [k.strip() for k in (item_keys or "").split(",") if k.strip()]
        if not keys and sorgu:
            zot = get_zotero_client()
            found = zot.items(q=sorgu, qmode="titleCreatorYear", limit=3)
            if isinstance(found, dict):
                found = found.get("items", [])
            for it in found or []:
                data = it.get("data") or it
                if data.get("key") and data.get("itemType") != "attachment":
                    keys.append(str(data["key"]))
                    break
        if not keys:
            return json.dumps(
                {"error": "item_keys veya (sonuç veren) sorgu gerekli"},
                ensure_ascii=False,
            )

        try:
            entries = await asyncio.to_thread(
                run_in_daemon, lambda: _csl_entries(keys), 30.0, "zotero-csl"
            )
        except BridgeTimeout as exc:
            return json.dumps({"error": f"Zotero API zaman aşımı: {exc}"}, ensure_ascii=False)

        texts: list[str] = []
        kaynakca_texts: list[str] = []
        isnad_hatalari: list[str] = []
        for entry, key in zip(entries, keys):
            forms = await asyncio.to_thread(
                run_in_daemon, lambda k=key: _isnad_forms_sync(k, locator), 30.0, "isnad"
            )
            if forms.get("_error"):
                isnad_hatalari.append(f"{key}: {forms['_error']}")
            texts.append(forms.get("dipnot") or _csl_fallback_text(entry["csl"]))
            kaynakca_texts.append(
                forms.get("kaynakca") or _csl_fallback_text(entry["csl"])
            )

        formatted = "; ".join(t for t in texts if t)

        pkg = DocxPackage(docx_path)
        konum_temiz = (konum or "").strip()
        isaret_var = bool(konum_temiz) and konum_temiz.lower() not in ("son", "end", "append")
        dipnot_modu = (atif_tipi or "").strip().lower() == "dipnot"

        # Not stilli (ör. İSNAD dipnotlu) atıf gerçek bir Word dipnotunda yaşar;
        # Zotero'nun citation.properties.noteIndex alanı dipnot numarasıdır.
        fid = pkg.next_footnote_id() if dipnot_modu else 0
        payload = build_citation_payload(
            entries, formatted_citation=formatted, note_index=fid
        )
        instruction = citation_instruction(payload)

        prefs_adet = 0
        mevcut_stil = pkg.document_style() or {}
        stil_kaynagi = "parametre"
        if not stil:
            if mevcut_stil.get("id"):
                stil = str(mevcut_stil["id"])
                stil_kaynagi = "belge"
            else:
                stil, yerel = zotero_varsayilan_stil()
                stil_kaynagi = "zotero_varsayilan"
        # Kullanıcı stili bir kez seçtiyse her belgede yeniden yazmayalım;
        # yalnızca belgede stil yoksa ya da farklıysa tercih alanlarını yaz.
        if stil_ayarla and (mevcut_stil.get("id") or "") != style_url(stil):
            prefs = prefs_instructions(
                build_prefs_json(
                    style=stil,
                    note_type=NOTE_TYPES.get(atif_tipi, 1),
                    locale=str(mevcut_stil.get("locale") or zotero_varsayilan_stil()[1]),
                )
            )
            pkg.replace_prefs(prefs)
            prefs_adet = len(prefs)

        uyarilar: list[str] = []
        if dipnot_modu:
            if isaret_var:
                yerlesti = pkg.add_footnote(
                    fid, instruction, formatted, marker=konum_temiz, font=yazi_tipi
                )
                if not yerlesti:
                    uyarilar.append(
                        f"işaret bulunamadı ('{konum_temiz}'); dipnot belge sonuna eklendi"
                    )
                    yerlesti = pkg.add_footnote(
                        fid, instruction, formatted, font=yazi_tipi
                    )
            else:
                yerlesti = pkg.add_footnote(fid, instruction, formatted, font=yazi_tipi)
        else:
            yerlesti = False
            if isaret_var:
                yerlesti = pkg.replace_marker(
                    konum_temiz, instruction, formatted, font=yazi_tipi
                )
                if not yerlesti:
                    uyarilar.append(
                        f"işaret bulunamadı ('{konum_temiz}'); atıf belge sonuna eklendi"
                    )
            if not yerlesti:
                pkg.append_field(instruction, formatted, yazi_tipi)

        bib_written = False
        if bibliyografya:
            pkg.append_field(
                bibliography_instruction(),
                "\n".join(t for t in kaynakca_texts if t),
                yazi_tipi,
            )
            bib_written = True

        out = pkg.save(backup=yedek)

        return json.dumps(
            {
                "ok": True,
                "docx": str(out),
                "yedek": str(out.with_suffix(out.suffix + ".bak")) if yedek else None,
                "citation_id": payload["citationID"],
                "item_keys": keys,
                "isaret_bulundu": yerlesti if isaret_var else None,
                "konum": "belge_sonu" if not yerlesti else konum_temiz,
                "atif_yeri": "dipnot" if dipnot_modu else "metin_ici",
                "dipnot_no": fid or None,
                "yazi_tipi": yazi_tipi,
                "gorunen_metin": formatted,
                "stil_alani_yazildi": prefs_adet,
                "stil": stil,
                "stil_kaynagi": stil_kaynagi if stil_ayarla else None,
                "belge_stili": pkg.document_style(),
                "kaynakca_alani": bib_written,
                "isnad_uyarilari": isnad_hatalari or None,
                "uyarilar": uyarilar or None,
                "sonraki_adim": (
                    "Word'de belgeyi açıp Zotero sekmesinden Refresh'e bas; Zotero "
                    "atıfı kendi alanı olarak tanır ve stile göre yeniden biçimlendirir."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    except WordFieldError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False
        )


async def zotero_word_atif_listele(docx_path: str) -> str:
    """Belgedeki Zotero atıf alanlarını, kaynakça alanını ve stili listeler."""
    from .word_citation import (
        DocxPackage,
        WordFieldError,
        is_bibliography_field,
        is_citation_field,
        is_prefs_field,
    )

    try:
        pkg = DocxPackage(docx_path)
        citations = [
            {
                "citation_id": f.citation_id,
                "item_keys": f.item_keys,
                "metin": f.result_text[:200],
            }
            for f in pkg.all_fields()
            if is_citation_field(f.instruction)
        ]
        fields = pkg.all_fields()
        return json.dumps(
            {
                "docx": str(pkg.path),
                "atif_sayisi": len(citations),
                "atiflar": citations,
                "kaynakca_alani": sum(1 for f in fields if is_bibliography_field(f.instruction)),
                "pref_alani": sum(1 for f in fields if is_prefs_field(f.instruction)),
                "belge_stili": pkg.document_style(),
            },
            ensure_ascii=False,
            indent=2,
        )
    except WordFieldError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


# ---------------------------------------------------------------- terim araştırma

def _mevzuat_hits(payload: Any, limit: int) -> list[dict[str, Any]]:
    """mevzuat_ara yanıtını sadeleştirir (alan adları sürümle değişebiliyor)."""
    rows: list[Any] = []
    if isinstance(payload, dict):
        for key in ("results", "items", "mevzuatlar", "data", "documents"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    elif isinstance(payload, list):
        rows = payload
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "id": row.get("mevzuat_id") or row.get("id") or row.get("documentId"),
                "ad": row.get("mevzuat_adi") or row.get("adi") or row.get("title"),
                "tur": row.get("mevzuat_turu") or row.get("tur") or row.get("type"),
                "no": row.get("mevzuat_no") or row.get("no"),
                "tarih": row.get("resmi_gazete_tarihi") or row.get("tarih") or row.get("date"),
            }
        )
    return out


def _snippets(payload: Any, limit: int = 5) -> list[str]:
    if isinstance(payload, dict):
        for key in ("snippets", "eslesmeler", "matches", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                out = []
                for row in value[:limit]:
                    text = row.get("text") if isinstance(row, dict) else row
                    if text:
                        out.append(" ".join(str(text).split())[:400])
                return out
    return []


async def terim_arastir(
    terim: str,
    mevzuat_ipucu: str = "",
    limit: int = 5,
    resmi_gazete_gun: int = 730,
    icerik_arama: bool = True,
    timeout_s: float = 240.0,
) -> str:
    """Bir terimin RESMÎ Türkçe kullanımını arar (mevzuat metni + Resmî Gazete).

    Ne zaman kullanılır: çeviride karşılığı bilinmeyen/şüpheli bir terim
    (özellikle hukuk terimi) varsa. `mevzuat_ara` yalnızca mevzuat
    BAŞLIKLARINI tarar; bu yüzden terim başlıkta geçmiyorsa `mevzuat_ipucu`
    ile ilgili kanunu ver (ör. terim='vatansızlık', ipucu='Vatandaşlık'):
    araç o mevzuatın METNİ içinde terimi arar ve resmî kullanım örneklerini
    döndürür. Bulunan resmî karşılık `glossary_add` ile kaynağıyla birlikte
    sözlüğe yazılmalıdır.

    Genel dil/alan terimleri için ayrıca web araması gerekir (TDK, alan
    literatürü); bu araç yalnızca yerel resmî kaynakları tarar.
    """
    from datetime import date, timedelta

    from .yargi_client import yargi_calls

    terim = (terim or "").strip()
    if not terim:
        return json.dumps({"error": "terim zorunlu"}, ensure_ascii=False)

    bugun = date.today()
    baslangic = (bugun - timedelta(days=max(1, resmi_gazete_gun))).isoformat()
    sorgu = (mevzuat_ipucu or terim).strip()

    try:
        results = await yargi_calls(
            [
                ("mevzuat_ara", {"query": sorgu, "sayfa_boyutu": max(1, min(20, limit))}),
                (
                    "resmi_gazete_ara",
                    {
                        "query": terim,
                        "fromDate": baslangic,
                        "toDate": bugun.isoformat(),
                        "maxResults": max(1, min(50, limit * 4)),
                    },
                ),
            ],
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"error": f"yargi: {type(exc).__name__}: {exc}"}, ensure_ascii=False
        )

    mevzuat_raw, gazete_raw = results[0], results[1]
    hits = _mevzuat_hits(mevzuat_raw, limit)

    ornek: list[str] = []
    icerik_hatasi = None
    if icerik_arama and hits:
        for hit in hits[:3]:
            if not hit.get("id"):
                continue
            try:
                icerik = await yargi_calls(
                    [
                        (
                            "mevzuat_icinde_ara",
                            {
                                "mevzuat_id": str(hit["id"]),
                                "anahtar_kelime": terim,
                                "maksimum_eslesme": 5,
                            },
                        )
                    ],
                    timeout=timeout_s,
                )
                found = _snippets(icerik[0])
            except Exception as exc:  # noqa: BLE001
                icerik_hatasi = f"{type(exc).__name__}: {exc}"
                continue
            if found:
                ornek = [f"[{hit.get('ad')}] {s}" for s in found]
                break

    gazete = _mevzuat_hits(gazete_raw, limit * 2)

    ipucu = None
    if not hits and not mevzuat_ipucu:
        ipucu = (
            "mevzuat_ara yalnızca BAŞLIKLARI tarar. Terim başlıkta geçmiyorsa "
            "ilgili kanun adını `mevzuat_ipucu` olarak ver (ör. 'Vatandaşlık'), "
            "araç metin içinde arar."
        )
    elif not ornek and hits:
        ipucu = "Mevzuat bulundu ama metin içinde terim geçmiyor; farklı bir terim/ipucu dene."

    return json.dumps(
        {
            "terim": terim,
            "sorgu": sorgu,
            "mevzuat": hits,
            "resmi_gazete": gazete,
            "ornek_kullanim": ornek,
            "icerik_hatasi": icerik_hatasi,
            "ipucu": ipucu,
            "sonraki_adim": (
                "Resmî kullanımdaki karşılığı seç, gerekiyorsa web aramasıyla "
                "(TDK/alan literatürü) doğrula ve `glossary_add` ile "
                "*kaynağıyla* sözlüğe yaz; karşılıksız terim bırakma."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- kayıt (health)

HEALTH_TIMEOUT_S = 6.0


async def _probe(fn: Any, timeout: float, label: str) -> str:
    """Tek bileşen kontrolü; hangi durumda olursa olsun asla bloke etmez."""
    try:
        await asyncio.to_thread(run_in_daemon, fn, timeout, label)
        return "ok"
    except BridgeTimeout as exc:
        return f"zaman aşımı: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"hata: {type(exc).__name__}: {exc}"


def _zotero_read_probe() -> None:
    get_zotero_client()


def _zotero_write_probe() -> None:
    if not Path(ZOTERO_COMMAND).exists():
        raise FileNotFoundError(f"zotero-mcp bulunamadı: {ZOTERO_COMMAND}")


def _shamela_files_probe() -> None:
    entry = Path(SHAMELA_ARGS[0])
    if not entry.exists():
        raise FileNotFoundError(f"şamile girişi yok: {entry}")
    if not shutil.which(SHAMELA_COMMAND):
        raise FileNotFoundError(f"'{SHAMELA_COMMAND}' PATH'te yok")


def _shamela_deep_probe() -> None:
    asyncio.run(shamela_get_book(1))


def _yargi_probe() -> None:
    import bedesten_mcp_module.client  # noqa: F401


def _makale_probe() -> None:
    if not Path(MAKALE_PATH).exists():
        raise FileNotFoundError(f"makale deposu yok: {MAKALE_PATH}")


def _isnad_probe() -> None:
    if not isnad.ISNAD_SCRIPT.exists():
        raise FileNotFoundError(f"isnad betiği yok: {isnad.ISNAD_SCRIPT}")


async def bridge_health(derin: bool = False, timeout_s: float = HEALTH_TIMEOUT_S) -> str:
    """Bağlı bileşenlerin durumu.

    Her bileşen ayrı ayrı ve eşzamanlı kontrol edilir; `timeout_s` saniyede
    kesin döner (asılı kalan bileşen 'zaman aşımı' olarak raporlanır, çağrı
    bloke olmaz). `derin=True` şamile'yi gerçekten çağırır (yavaş).
    """
    specs: list[tuple[str, Any]] = [
        ("zotero_read", _zotero_read_probe),
        ("zotero_write", _zotero_write_probe),
        ("shamela", _shamela_deep_probe if derin else _shamela_files_probe),
        ("yargi", _yargi_probe),
        ("makale", _makale_probe),
        ("isnad_script", _isnad_probe),
    ]
    results = await asyncio.gather(
        *(_probe(fn, timeout_s, name) for name, fn in specs)
    )
    components = {name: value for (name, _), value in zip(specs, results)}
    sorunlu = [name for name, value in components.items() if value != "ok"]
    try:
        acik = len(list_improvements(status="acik"))
    except Exception:  # noqa: BLE001
        acik = None
    return json.dumps(
        {
            "version": __version__,
            "derin": derin,
            "components": components,
            "improvements_acik": acik,
            "ozet": "tüm bileşenler ok" if not sorunlu else f"sorunlu: {', '.join(sorunlu)}",
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- MCP prompt'ları

@mcp.prompt()
def isnad_kunye_akisi(item_key: str = "", shamela_book_id: int = 0, page: str = "") -> str:
    """Zotero veya Şamile kaynağından İSNAD künyesi üretme akışı."""
    return (
        "İSNAD künyesi üretim akışı:\n"
        f"1. Kaynağı belirle (item_key={item_key or '-'}, "
        f"shamela_book_id={shamela_book_id or '-'}).\n"
        f"2. `isnad_kunye` çağır (page={page or '-'}).\n"
        "3. Dönen biçimleri isnad-kurallari.md'ye karşı GÖZLE doğrula; "
        "eksik alan UYDURMA, kullanıcıya bildir.\n"
        "4. Kaynak Zotero'da yoksa önce Zotero'ya item ekle, sonra künye üret."
    )


@mcp.prompt()
def yargi_makale_akisi(sorgu: str = "", slug: str = "") -> str:
    """Bedesten kararını bulup makale belgesine kaynak olarak ekleme akışı."""
    return (
        "Yargı → makale akışı:\n"
        f"1. `yargi_makale_cek(sorgu=\"{sorgu or '...'}\", slug=\"{slug or '...'}\")` "
        "ile karar metnini belge klasörüne yaz.\n"
        "2. Karar birden çoksa `yargi` MCP'sinden document_id al, "
        "`yargi_makale_cek` çağrısını document_id ile tekrarla.\n"
        "3. Kararı kütüphaneye de almak için `yargi_zotero_kaydet` kullan.\n"
        "4. Künyeyi İSNAD biçimine çevirmek için `isnad_kunye` akışını uygula."
    )


# ---------------------------------------------------------------- tool kaydı

mcp.tool()(citation_search)
mcp.tool()(isnad_kunye)
mcp.tool()(citation_export)
mcp.tool()(yargi_makale_cek)
mcp.tool()(yargi_zotero_kaydet)
mcp.tool()(shamela_makale_ata)
mcp.tool()(makale_durum)
mcp.tool()(zotero_word_atif)
mcp.tool()(zotero_word_atif_listele)
mcp.tool()(terim_arastir)
mcp.tool()(bridge_health)
mcp.tool()(improvement_log)
mcp.tool()(improvement_list)
mcp.tool()(improvement_resolve)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

