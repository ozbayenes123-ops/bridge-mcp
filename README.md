# bridge-mcp

Yerel MCP'leri birleştiren köprü sunucusu. Karar LLM'de (orkestratör);
bridge yalnızca tekrarlanan zincirleri tek çağrıya indirir.

## Tool'lar

| Tool | Zincir | Ne yapar |
|---|---|---|
| `citation_search(query)` | Zotero → Shamela | Önce Zotero'da arar, boşsa Shamela katalogunda arar; sonuçlar kaynak etiketli. |
| `isnad_kunye(item_key \| shamela_book_id, page)` | Zotero/Shamela → isnad_word.py | Normalize üstveri + dipnot/kısa/kaynakça formları. Çıktı gözle `isnad-kurallari.md`'ye karşı doğrulanmalı. |
| `citation_export(log_path, fmt)` | isnad_word.py | Atıf günlüğünden RIS/CSL-JSON üretir (Zotero'ya File>Import elle yapılır). |
| `yargi_makale_cek(sorgu, slug, document_id?, birim_adi?)` | Bedesten → makale | Karar markdown'ını `C:\dev\mcp\makale\documents\<slug>\` altına yazar + `config.json` üretir. |
| `bridge_health()` | — | Bileşenlerin (Zotero, Shamela spawn, yargi import, isnad betiği) durumunu döndürür. |

## Mimari

- `zotero_mcp` (`C:\dev\mcp\zotero-mcp-src`) ve `bedesten_mcp_module` / `emsal_mcp_module`
  (`C:\dev\mcp\yargi-mcp`) **sys.path ile import edilir**; ayrı kurulum gerekmez.
  Yollar `YARGI_MCP_PATH` ve `ZOTERO_MCP_SRC` env ile değiştirilebilir.
- Shamela, `shamela_client.py` üzerinden her çağrıda taze bir MCP stdio oturumu
  ile konuşur (`node C:\dev\mcp\shamela-mcp\dist\index.js`).
- Bedesten rate-limit bucket'ı bridge process'ine özeldir; yargi-mcp server ile
  aynı IP'den paralel istek varsa `BEDESTEN_RATE_*` env ile yavaşlatın.

## Çalıştırma

```
uv sync --project C:\dev\mcp\bridge-mcp
uv run --project C:\dev\mcp\bridge-mcp bridge-mcp
```

Command Code kaydı: `~/.commandcode/mcp.json` → `bridge` (stdio).
