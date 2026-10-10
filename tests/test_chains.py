"""Yeni zincirlerin saf yardımcıları ve zaman aşımı davranışı."""

import asyncio
import json
import time

import pytest

from bridge_mcp._util import BridgeTimeout, run_in_daemon
from bridge_mcp.makale_docs import slugify
from bridge_mcp.zotero_client import ZoteroWriteError, parse_new_key


# --------------------------------------------------------------- run_in_daemon

def test_run_in_daemon_returns_value():
    assert run_in_daemon(lambda: 42, 5, "t") == 42


def test_run_in_daemon_propagates_error():
    def boom():
        raise ValueError("patladı")

    with pytest.raises(ValueError):
        run_in_daemon(boom, 5, "t")


def test_run_in_daemon_times_out_without_blocking():
    """Asılı kalan bir iş bile süresi dolunca çağrıyı serbest bırakmalı."""
    started = time.time()
    with pytest.raises(BridgeTimeout):
        run_in_daemon(lambda: time.sleep(30), 0.3, "t")
    assert time.time() - started < 5


# --------------------------------------------------------------- zotero_client

def test_parse_new_key_reads_item_key():
    assert parse_new_key("Created case — key: `ABCD1234`") == "ABCD1234"


def test_parse_new_key_raises_on_error_text():
    with pytest.raises(ZoteroWriteError):
        parse_new_key("Error creating item: field missing")


def test_parse_new_key_raises_without_key():
    with pytest.raises(ZoteroWriteError):
        parse_new_key("tamam")


# --------------------------------------------------------------- makale_docs

def test_slugify_turkish_text():
    assert slugify("Yargıtay 9. HD E. 2020/123") == "yargitay-9-hd-e-2020-123"
    assert slugify("") == "belge"


# --------------------------------------------------------------- şamile yanıt ayrıştırma

def test_find_first_walks_nested_payload():
    from bridge_mcp.server import _first_int, _page_text

    hits = {"result": {"hits": [{"book": {"id": 7}, "page_id": "1234", "body": "metin"}]}}
    assert _first_int(hits, ("page_id", "pageId")) == 1234

    page = {"page": {"body": "السلام", "printed_page": 55, "part": "1"}}
    text, printed = _page_text(page)
    assert text == "السلام"
    assert printed == "1/55"


def test_first_int_returns_zero_when_absent():
    from bridge_mcp.server import _first_int

    assert _first_int({"a": {"b": []}}, ("page_id",)) == 0


# --------------------------------------------------------------- health

def test_health_summary_shape_and_timeout_bound(monkeypatch):
    """bridge_health asılı bir bileşen yüzünden bloke olmamalı."""
    from bridge_mcp import server

    monkeypatch.setattr(
        server, "_zotero_read_probe", lambda: time.sleep(30)
    )
    started = time.time()
    payload = json.loads(asyncio.run(server.bridge_health(timeout_s=0.5)))
    elapsed = time.time() - started

    assert elapsed < 10, "health kontrolü asılı kaldı"
    assert payload["components"]["zotero_read"].startswith("zaman aşımı")
    assert "ozet" in payload and "improvements_acik" in payload


# --------------------------------------------------------------- karar üstverisi

def test_meta_from_markdown_extracts_court_and_numbers():
    from bridge_mcp.server import _meta_from_markdown

    content = (
        "İstanbul 19. Asliye Ticaret Mahkemesi\n"
        "Esas No: 2026/1848\nKarar No: 2026/756\nKarar Tarihi: 09.10.2026\n"
    )
    meta = _meta_from_markdown(content)
    assert meta["esasNo"] == "2026/1848"
    assert meta["kararNo"] == "2026/756"
    assert meta["kararTarihiStr"] == "09.10.2026"
    # Mahkeme adı şehir + daire bilgisini kaybetmemeli.
    assert meta["birimAdi"] == "İstanbul 19. Asliye Ticaret Mahkemesi"


def test_meta_from_markdown_returns_empty_when_absent():
    from bridge_mcp.server import _meta_from_markdown

    assert _meta_from_markdown("hiçbir şey yok") == {}


def test_item_body_uses_casename_for_case_type():
    from bridge_mcp.server import _item_body

    chosen = {"birimAdi": "Yargıtay 9. HD", "esasNo": "2020/1", "kararNo": "2021/2",
              "kararTarihiStr": "01.02.2021", "documentId": "9"}
    doc = {"source_url": "https://example.invalid/x"}
    case_body = _item_body("case", chosen, doc)
    assert case_body["caseName"] == "Yargıtay 9. HD E. 2020/1 K. 2021/2"
    assert "title" not in case_body, "case tipinde 'title' gönderilirse Zotero 'Untitled' gösterir"
    assert case_body["court"] == "Yargıtay 9. HD"

    doc_body = _item_body("document", chosen, doc)
    assert doc_body["title"] == "Yargıtay 9. HD E. 2020/1 K. 2021/2"
    assert "date" in doc_body
