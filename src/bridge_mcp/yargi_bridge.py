"""yargi-mcp istemcilerini makale pipeline'ına bağlayan köprü.

Bedesten/Emsal kararlarını arar, seçilen kararın markdown'ını
makale belge köküne (documents/<slug>/) yazar.
"""

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from bedesten_mcp_module.client import BedestenApiClient, BedestenRateLimited
from bedesten_mcp_module.models import (
    BedestenSearchData,
    BedestenSearchRequest,
)
from emsal_mcp_module.client import EmsalApiClient, EmsalRateLimited
from emsal_mcp_module.models import EmsalSearchRequest

MAKALE_DOCS = Path(r"C:\dev\mcp\makale\documents")

DEFAULT_COURTS = [
    "YARGITAYKARARI",
    "DANISTAYKARARI",
    "YERELHUKUK",
    "ISTINAFHUKUK",
    "KYB",
]


class YargiBridgeError(RuntimeError):
    pass


def slugify(text: str, fallback: str = "karar") -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:48] or fallback


async def bedesten_search(
    phrase: str,
    courts: list[str] | None = None,
    birim_adi: str = "ALL",
    page: int = 1,
) -> dict[str, Any]:
    client = BedestenApiClient()
    try:
        data = BedestenSearchData(
            pageSize=10,
            pageNumber=max(1, page),
            itemTypeList=courts or DEFAULT_COURTS,
            phrase=phrase,
            birimAdi=birim_adi,
        )
        resp = await client.search_documents(BedestenSearchRequest(data=data))
        entries = (resp.data.emsalKararList if resp.data else []) or []
        return {
            "total": resp.data.total if resp.data else 0,
            "entries": [e.model_dump() for e in entries],
        }
    finally:
        await client.close_client_session()


async def bedesten_document(document_id: str) -> dict[str, Any]:
    client = BedestenApiClient()
    try:
        doc = await client.get_document_as_markdown(document_id)
        return doc.model_dump()
    finally:
        await client.close_client_session()


async def emsal_search(keyword: str, start_date: str = "", end_date: str = "") -> dict[str, Any]:
    client = EmsalApiClient()
    try:
        req = EmsalSearchRequest(keyword=keyword, start_date=start_date, end_date=end_date)
        resp = await client.search_detailed_decisions(req)
        return resp.model_dump(mode="json")
    finally:
        await client.close_client_session()


async def cek_ve_yaz(
    phrase: str,
    slug: str,
    document_id: str = "",
    courts: list[str] | None = None,
    birim_adi: str = "ALL",
) -> dict[str, Any]:
    """Karar arar (document_id verilmezse ilk sonucu alır), makale documents/'a yazar."""
    if not phrase:
        raise YargiBridgeError("sorgu (phrase) zorunlu")

    if document_id:
        doc = await bedesten_document(document_id)
        chosen = {"documentId": document_id, "birimAdi": "", "kararNo": "", "esasNo": "", "kararTarihiStr": ""}
    else:
        results = await bedesten_search(phrase, courts=courts, birim_adi=birim_adi)
        entries = results["entries"]
        if not entries:
            return {"found": False, "query": phrase, "total": results["total"]}
        entry = entries[0]
        chosen = entry
        doc = await bedesten_document(entry["documentId"])

    content = doc.get("markdown_content") or ""
    if not content:
        raise YargiBridgeError(f"karar içeriği boş döndü (id={doc.get('documentId')})")

    slug = slugify(slug or phrase)
    doc_dir = MAKALE_DOCS / slug
    doc_dir.mkdir(parents=True, exist_ok=True)
    md_path = doc_dir / f"{slug}_karar.md"
    md_path.write_text(content, encoding="utf-8")

    config = {
        "document_name": chosen.get("kararNo") or phrase,
        "style": "academic",
        "numbered_paragraphs": False,
        "glossary": {},
        "bridge_metadata": {
            "source": "bedesten",
            "document_id": chosen.get("documentId"),
            "birim_adi": chosen.get("birimAdi"),
            "esas_no": chosen.get("esasNo"),
            "karar_no": chosen.get("kararNo"),
            "karar_tarihi": chosen.get("kararTarihiStr") or chosen.get("kararTarihi"),
            "source_url": doc.get("source_url"),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        },
    }
    config_path = doc_dir / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "found": True,
        "slug": slug,
        "markdown_path": str(md_path),
        "config_path": str(config_path),
        "kaynak": config["bridge_metadata"],
        "content_chars": len(content),
    }


__all__ = [
    "BedestenRateLimited",
    "EmsalRateLimited",
    "YargiBridgeError",
    "bedesten_search",
    "bedesten_document",
    "emsal_search",
    "cek_ve_yaz",
    "slugify",
]
