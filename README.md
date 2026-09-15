# bridge-mcp

Yerel MCP'leri birleştiren köprü sunucusu. Karar LLM'de (orkestratör);
bridge yalnızca tekrarlanan zincirleri tek çağrıya indirir.

## Tool'lar

| Tool | Zincir | Ne yapar |
|---|---|---|
| `citation_search(query)` | Zotero → Shamela | Önce Zotero'da arar, boşsa Shamela katalogunda arar; sonuçlar kaynak etiketli. |
| `isnad_kunye(item_key \| shamela_book_id, page)` | Zotero/Shamela → isnad_word.py | Normalize üstveri + dipnot/kısa/kaynakça formları. Çıktı gözle `isnad-kurallari.md`'ye karşı doğrulanmalı. |
| `citation_export(log_path, fmt)` | isnad_word.py | Atıf günlüğünden RIS/CSL-JSON üretir (Zotero'ya File > Import elle yapılır). |
| `yargi_makale_cek(sorgu, slug, document_id?, birim_adi?)` | Bedesten → makale | Karar markdown'ını `MAKALE_DOCS/<slug>/` altına yazar + `config.json` üretir. |
| `bridge_health()` | — | Bileşenlerin (Zotero, Shamela spawn, yargi import, isnad betiği) durumunu döndürür. |
| `improvement_log(konu, tip, hedef, kaynak_tool, detay)` | — | İşlem sonunda tespit edilen eksiklik/hata/özellik fikrini `data/improvements.jsonl`'a kaydeder. |
| `improvement_list(status, hedef)` | — | Açık/tüm kayıtları listeler. |
| `improvement_resolve(id, durum)` | — | Kaydı yapıldı/iptal olarak kapatır. Düzeltme kararı orkestratördedir. |

## Kurulum

Ön koşullar: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+ (Shamela için).

```powershell
uv sync --project <KURULUM_KÖKÜ>\bridge-mcp
uv run --project <KURULUM_KÖKÜ>\bridge-mcp bridge-mcp
```

Command Code kaydı (`~/.commandcode/mcp.json`); `cmdc-stack` deposundaki
`scripts/register-mcp.ps1` bu kaydı sizin için üretir:

```json
{
  "mcpServers": {
    "bridge": {
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "--project", "<KURULUM_KÖKÜ>\\bridge-mcp", "bridge-mcp"]
    }
  }
}
```

## Yapılandırma

Tüm yollar ortam değişkeniyle geçilebilir; varsayılanlar bu deponun kardeş
dizinleridir (yani `<KURULUM_KÖKÜ>` altındaki diğer MCP depoları).

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `YARGI_MCP_PATH` | `<kurulum kökü>/yargi-mcp` | `bedesten_mcp_module` / `emsal_mcp_module` buradan import edilir |
| `ZOTERO_MCP_SRC` | `<kurulum kökü>/zotero-mcp-src` | `zotero_mcp` paketi buradan import edilir |
| `SHAMELA_ENTRY` | `<kurulum kökü>/shamela-mcp/dist/index.js` | Shamela MCP stdio girişi |
| `SHAMELA_COMMAND` | `node` | Shamela'yı çalıştıran komut |
| `SHAMELA_INSTALL_ROOT` | `C:\shamela4` (varsa) | Shamela 4 kurulum kökü |
| `SHAMELA_JRE` | PATH'teki `java` | Shamela'nın kullandığı Java yorumlayıcısı |
| `ISNAD_WORD_SCRIPT` | `~/.commandcode/skills/isnad-word/scripts/isnad_word.py` | Kanonik İSNAD betiği |
| `MAKALE_DOCS` | `<kurulum kökü>/makale/documents` | `yargi_makale_cek` çıktı kökü |

Not: `yargi-mcp` sunucusuyla aynı IP'den paralel istek atılırsa Bedesten
rate-limit bütçesi paylaşılır; gerekirse `BEDESTEN_RATE_*` ile yavaşlatın.

## Mimari

- `zotero_mcp` ile `bedesten_mcp_module` / `emsal_mcp_module` **sys.path ile
  import edilir**; ayrı kurulum gerekmez.
- Shamela, `shamela_client.py` üzerinden her çağrıda taze bir MCP stdio
  oturumu açar.
- Bridge karar vermez: hangi kaynağın kullanılacağını orkestratör (LLM) seçer.
